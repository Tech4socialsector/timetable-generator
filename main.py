#from src.test_data_factory import create_demo_scenario, create_stress_test_scenario
from src.solver import TimetableSolver
from src.data_loader import ExcelDataLoader
from src.domain import WorkWeekConfig, TimeSlot, RoomType

import sys
import pandas as pd
from pathlib import Path
import os, shutil
import json
from datetime import datetime

def compute_free_cohorts(time_table, scenario):
    """
    For each COMPLETE category entry, compute which eligible cohorts
    are free at that slot (have no other session scheduled in an
    overlapping term at the same day+slot).
    Returns a dict keyed by the entry's Session+Assigned Day+Assigned Slot
    mapping to a list of free cohort IDs.
    """
    from collections import defaultdict

    cat_map = {c.id: c for c in scenario.course_categories}

    # Build {(day, slot, term_id): set of cohort_ids that are busy}
    # A cohort is busy if it has ANY session at that (day, slot) in an overlapping term
    busy = defaultdict(set)
    for entry in time_table:
        if not entry.get("Is Start Slot", True):
            continue
        day   = entry.get("Assigned Day")
        slot  = entry.get("Assigned Slot")
        term  = entry.get("Term", "FULL")
        dur   = entry.get("Number of Slot", 1)
        cohorts = entry.get("Eligible Cohorts", [])
        # Mark all occupied slots (duration-aware)
        for d in range(dur):
            for cohort in cohorts:
                busy[(day, slot + d, term)].add(cohort.upper())

    # Now for each COMPLETE entry, find which eligible cohorts are free
    result = {}
    for entry in time_table:
        if not entry.get("Is Start Slot", True):
            continue
        cat_id = entry.get("Category", "")
        cat = cat_map.get(cat_id)
        if not cat or cat.choice_type.upper() != "COMPLETE":
            result[id(entry)] = None  # not COMPLETE — skip
            continue

        day   = entry.get("Assigned Day")
        slot  = entry.get("Assigned Slot")
        term  = entry.get("Term", "FULL")
        dur   = entry.get("Number of Slot", 1)
        eligible = [c.upper() for c in entry.get("Eligible Cohorts", [])]

        # A cohort is free if it has no busy entry at ANY of the
        # slots this session occupies, in any overlapping term
        free = []
        for cohort in eligible:
            cohort_free = True
            for d in range(dur):
                # Check all terms that overlap with this session's term
                for (b_day, b_slot, b_term), b_cohorts in busy.items():
                    if (b_day == day and b_slot == slot + d
                            and cohort in b_cohorts
                            and scenario.terms_overlap(term, b_term)
                            and b_term != term):  # exclude self
                        cohort_free = False
                        break
                if not cohort_free:
                    break
            if cohort_free:
                free.append(cohort)

        result[id(entry)] = sorted(free)

    return result

def main():
    print("Initializing Timetabling System...")
    #INPUT_FILE = "src/data/apu_timetable_data.xlsx"
    #INPUT_FILE = "src/data/Timetable for July 2026_20 LAST.xlsx"
    #INPUT_FILE = "src/data/BHPL Jul  26_ Course list template_timetable 2104.xlsx"
    #INPUT_FILE = "src/data/BHPL Jul  26_ Course list template_timetable 2005.xlsx"
    #INPUT_FILE = "src/data/BHPL Jul  26_ Course list template_timetable 2005_26052026_PG Version.xlsx"
    #INPUT_FILE = "src/data/BHPL Jul  26_ Course list template_timetable 2005_26052026.xlsx"
    INPUT_FILE = "src/data/BHPL Jul  26_ Course list template_timetable 2005_26052026_PG Version new1.xlsx"
    datetime_str = datetime.today().strftime('%d%m_%Y%H%M')
    SOLUTION_HINT_SAVE_FILE = f"src/data/solution_hint_{datetime_str}.json"
    SOLUTION_HINT_FILE = f"src/data/solution_hint.json"
    TIMETABLE_OUTPUT_DIR = f"src/data/timetables_{datetime_str}"
    dirname = os.path.dirname(INPUT_FILE)      # /a/b
    base, ext = os.path.splitext(os.path.basename(INPUT_FILE))  # ('c', '.txt')
    OUTPUT_FILE = os.path.join(dirname, base + "_with_timetable" + ext)
    #COHORTS_TO_OUTPUT = ['MADEV25', 'MADEV26', 'BSCPHY23', 'BSCPHY24', 'BSCPHY25', 'BSCPHY26']  # e.g. ['MADEV25', 'BSCPHY24'] or None for all
    COHORTS_TO_OUTPUT = ['BSBIO25']
    #COHORTS_TO_OUTPUT = []
    slot_time_map = {
        0: "6:30-8:00",
        1: "8:30-10:30",
        2: "10:45:12:45",
        3: "1:45:3:45",
        4: "4:00:6:00",
        5: "6:45-8:45",
    }

    try:
        config = WorkWeekConfig(
            days_per_week=6,
            slots_per_day=6,
            lunch_slots=[],  # e.g., Slots 3 and 4 (12:00 - 14:00) are blocked
            meeting_slots=[
                #TimeSlot(day_index=1, slot_index=2) # Friday last slot is a meeting
            ]
        )        
        loader = ExcelDataLoader(INPUT_FILE)
        scenario = loader.load_scenario(config)
        if not scenario:
            sys.exit(1)
        #print(f"Successfully loaded {len(scenario.courses)} courses, {len(scenario.sections)} schedulable sections and {len(scenario.locations)} rooms.")
    except Exception as e:
        print(f"Error loading Excel file: {e}")
        sys.exit(1)    
    #sys.exit(0)
    # 3. Initialize the Solver
    # relax_on_failure=True allows the solver to show conflicts instead of just saying 'No'
    METADATA_FILE = "src/data/solution_metadata.json"
    #FIRST_TIMEOUT = 5400    # 90 minutes
    FIRST_TIMEOUT = 3600    # 60 minutes
    #FIRST_TIMEOUT = 900    # 15 minutes
    #FIRST_TIMEOUT = 300    
    FOLLOWUP_TIMEOUT = 1800  # 30 minutes
    FOLLOWUP_TIMEOUT = 900  # 15 minutes
    MAX_RUNS = 1
    TARGET_OBJECTIVE = 0

    solution = None
    best_objective = float('inf')
    for run_number in range(1, MAX_RUNS + 1):
        print(f"\n{'='*60}")
        print(f"SOLVER RUN {run_number}")

        # Determine timeout and seed
        timeout = FIRST_TIMEOUT if run_number == 1 else FOLLOWUP_TIMEOUT
        seed = None
        if run_number > 1 and os.path.exists(METADATA_FILE):
            with open(METADATA_FILE) as f:
                meta = json.load(f)
            if meta.get("stalled", False):
                import time
                seed = int(time.time()) % 2**31
                print(f"Previous run stalled — new seed {seed}")
            else:
                seed = meta.get("seed_used")
                print(f"Previous run improving — reusing seed {seed}")
        print(f"Timeout: {timeout}s, Best so far: {best_objective}")
        print(f"{'='*60}")

        # Build fresh model
        solver = TimetableSolver(scenario)
        solver.create_variables()
        solver.add_constraints()
        #sys.exit(0)

        # Load hint from best previous run
        if os.path.exists(SOLUTION_HINT_FILE):
            solver.load_solution_hint(SOLUTION_HINT_FILE)

        solver.run_preflight_audit()

        # Solve
        print("Searching for optimal schedule...")
        result = solver.solve(
            timeout_seconds=timeout,
            solution_hint_file=SOLUTION_HINT_FILE,
            metadata_file=METADATA_FILE,
            seed=seed
        )
        if result is None:
            break

        # Check progress
        if os.path.exists(METADATA_FILE):
            with open(METADATA_FILE) as f:
                meta = json.load(f)
            new_objective = meta.get("best_objective", float('inf'))
            if new_objective < best_objective:
                best_objective = new_objective
                solution = result
                print(f"✅ New best: {best_objective}")
                # Save timestamped copy of best hint
                import shutil as _shutil
                if os.path.exists(SOLUTION_HINT_FILE):
                    _shutil.copy(SOLUTION_HINT_FILE, SOLUTION_HINT_SAVE_FILE)
            else:
                print(f"No improvement this run ({new_objective} vs {best_objective})")
                if run_number > 1:
                    print("Stopping loop.")
                    break

        if result is None and run_number == 1:
            print("First run found no solution. Check data and constraints.")
            break

        if best_objective <= TARGET_OBJECTIVE:
            print(f"Target objective {TARGET_OBJECTIVE} reached. Stopping.")
            break
    if solution:
        #with open("a.json", "w") as f:
        #    json.dump(solution, f, indent=4)
        time_table = []
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        for entry in sorted(solution, key=lambda x: (x['day_index'], x['slot_index'])):
            section = entry['section']
            course = scenario.get_course_by_id(section.course_id)
            location = scenario.get_location_by_id(str(entry['room_id']))
            #print(location.name, location.classroom_capacity)
            duration = entry['duration']
            for d in range(duration):
                time_table.append({
                    "Course name": course.name,
                    "Category": entry["section"].category,
                    "Required classroom size": course.required_classroom_size,
                    "Required Lab type": course.required_lab_type,
                    "Theory sessions": course.theory_durations,
                    "Lab sessions": course.lab_durations,
                    "Faculty": ', '.join(entry["section"].faculty_ids),
                    "Assigned Day": days[entry['day_index']],
                    "Assigned Slot": entry['slot_index'] + d,
                    "Session": entry['section_id'],
                    "Assigned Room": location.name,
                    "Assigned Room Capacity": location.classroom_capacity if (location and location.type == RoomType.CLASSROOM) else "",
                    "Programmes": ",".join(course.program_ids) if course.program_ids else "",
                    "Term": entry["section"].term_id,
                    "Number of Slot": entry['duration'],
                    "Is Start Slot": d == 0,
                    "Eligible Cohorts": section.eligible_cohorts,
                    "Term": entry["section"].term_id,
                    "faculty_ids": entry["section"].faculty_ids,
                })            
            # time_table.append({
            #     "Course name": course.name,
            #     "Category": entry["section"].category, 
            #     "Required classroom size": course.required_classroom_size, 
            #     "Required Lab type": course.required_lab_type, 
            #     "Theory sessions": course.theory_durations,
            #     "Lab sessions": course.lab_durations,
            #     "Faculty": ', '.join(entry["section"].faculty_ids),
            #     "Assigned Day": days[entry['day_index']], 
            #     "Assigned Slot": entry['slot_index'],
            #     "Session": entry['section_id'],                 
            #     "Assigned Room": entry['room_id'],
            #     "Number of Slot": entry['duration'],
            #     "Eligible Cohorts": section.eligible_cohorts
            # })
            #print(f"Day {entry['day_index']} Slot {entry['slot_index']}: "
            #    f"{entry['section_id']} in {entry['room_id']} ({entry['duration']} slots)")

        # Populate Free Cohorts for COMPLETE entries
        print("Populating free cohorts...")
        free_cohorts_map = compute_free_cohorts(time_table, scenario)
        for entry in time_table:
            entry["Free Cohorts"] = ', '.join(free_cohorts_map.get(id(entry)) or []) \
                                    if free_cohorts_map.get(id(entry)) is not None else ''
            
        verify_timetable_constraints(config, scenario, time_table)
        df = pd.DataFrame(time_table)
        #print(df.iloc[1])
        #print(df.iloc[2])
        try:
            os.makedirs(TIMETABLE_OUTPUT_DIR, exist_ok=True)
            shutil.copy(INPUT_FILE, OUTPUT_FILE)
            with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                df.to_excel(writer, sheet_name='Timetable', index=False)
                generate_skeleton(time_table, config).to_excel(writer, sheet_name='Skeleton_FULL', index=False)
                # Cohort skeleton and timetable sheets
                cohorts_to_write = (
                    [c.id for c in scenario.cohorts]
                    if COHORTS_TO_OUTPUT is None
                    else COHORTS_TO_OUTPUT
                )
                for cohort_id in cohorts_to_write:
                    generate_cohort_excel_sheets(
                        cohort_id, time_table, scenario, config, writer)                
                # for term in scenario.terms:
                #     if term.term_id.upper() == 'FULL':
                #         continue  # already written above                    
                #     term_tt = [e for e in time_table if _entry_in_term(e, term, scenario.terms)]
                #     skeleton_df = generate_skeleton(term_tt, config)
                #     sheet_name = f"Skeleton_{term.term_id}"[:31]
                #     skeleton_df.to_excel(writer, sheet_name=sheet_name, index=False)
            #generate_pdf_timetables(time_table, scenario, config, 
            #                        output_dir=TIMETABLE_OUTPUT_DIR,
            #                        slot_time_map=slot_time_map)
        except FileNotFoundError:
            with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Timetable', index=False)
                # Write full-term skeleton unconditionally
                generate_skeleton(time_table, config).to_excel(
                    writer, sheet_name='Skeleton_FULL', index=False)
                # Cohort skeleton and timetable sheets
                cohorts_to_write = (
                    [c.id for c in scenario.cohorts]
                    if COHORTS_TO_OUTPUT is None
                    else COHORTS_TO_OUTPUT
                )
                for cohort_id in cohorts_to_write:
                    generate_cohort_excel_sheets(
                        cohort_id, time_table, scenario, config, writer)                                 
                # for term in scenario.terms:
                #     if term.term_id.upper() == 'FULL':
                #         continue  # already written above                    
                #     term_tt = [e for e in time_table if _entry_in_term(e, term, scenario.terms)]
                #     skeleton_df = generate_skeleton(term_tt, config)
                #     sheet_name = f"Skeleton_{term.term_id}"[:31]
                #     skeleton_df.to_excel(writer, sheet_name=sheet_name, index=False)
            #generate_pdf_timetables(time_table, scenario, config, 
            #                        output_dir=TIMETABLE_OUTPUT_DIR,
            #                        slot_time_map=slot_time_map)                    
    else:
        print("No solution found.")


def verify_timetable_constraints(config, scenario, time_table):
    verify_faculty_availability_constraints(config, scenario, time_table)
    verify_faculty_double_booking_constraints(config, scenario, time_table)
    verify_room_capacity_constraints(config, scenario, time_table)
    verify_room_types_constraints(config, scenario, time_table)
    verify_room_double_booking_constraints(config, scenario, time_table)
    verify_daily_distribution_constraints(config, scenario, time_table)
    verify_every_session_has_room(config, scenario, time_table)
    verify_no_cohort_conflicts_constraints(config, scenario, time_table)
    
def verify_faculty_availability_constraints(config, scenario, time_table):
    violations = []
    
    faculty_map = {f.id: f for f in scenario.faculty}
    
    for entry in time_table:
        section = entry.get("Section") or entry.get("session")
        if isinstance(section, str):
            section = scenario.get_section_by_id(section)
        if not section:
            continue
            
           
        day_index = entry.get("Assigned Day")
        slot_index = entry.get("Assigned Slot")
        
        if isinstance(day_index, str):
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_index = days.index(day_index) if day_index in days else day_index
            
        duration = entry.get("Number of Slot", 1)
        
        for faculty_id in section.faculty_ids:
            faculty = faculty_map.get(faculty_id)
            if not faculty:
                violations.append(f"Faculty {faculty_id} not found in scenario")
                continue
            available_set = {(s.day_index, s.slot_index) for s in faculty.available_slots}
            for d in range(duration):
                check_slot = (day_index, slot_index + d)
                if check_slot not in available_set:
                    violations.append(
                        f"Faculty {faculty_id} ({faculty.name}) assigned to {section.id} "
                        f"at day {day_index} slot {slot_index + d} but not available."
                    )
    
    if violations:
        print("FACULTY AVAILABILITY CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("Faculty availability constraints: PASSED")
        return True

def verify_faculty_double_booking_constraints(config, scenario, time_table):
    violations = []
    
    faculty_sessions = {}
    
    for entry in time_table:
        section = entry.get("Section") or entry.get("session")
        if isinstance(section, str):
            section = scenario.get_section_by_id(section)
        if not section:
            continue
            

        day_index = entry.get("Assigned Day")
        slot_index = entry.get("Assigned Slot")
        
        if isinstance(day_index, str):
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_index = days.index(day_index) if day_index in days else day_index
            
        duration = entry.get("Number of Slot", 1)

        term_id = entry.get("Term", "FULL")
        for faculty_id in section.faculty_ids:
            for d in range(duration):
                slot_key = (day_index, slot_index + d)
                faculty_sessions.setdefault(faculty_id, {}).setdefault(slot_key, []).append((section.id, term_id))
    
    for faculty_id, slots in faculty_sessions.items():
        for slot_key, entries in slots.items():
            if len(entries) > 1:
                for a in range(len(entries)):
                    for b in range(a + 1, len(entries)):
                        sec_a, term_a = entries[a]
                        sec_b, term_b = entries[b]
                        if scenario.terms_overlap(term_a, term_b):
                            violations.append(
                                f"Faculty {faculty_id} has double booking at day {slot_key[0]}, slot {slot_key[1]}: "
                                f"sections {sec_a} ({term_a}) and {sec_b} ({term_b})"
                            )
    
    if violations:
        print("FACULTY DOUBLE BOOKING CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("Faculty double booking constraints: PASSED")
        return True

def verify_room_capacity_constraints(config, scenario, time_table):
    violations = []
    
    location_map = {loc.id: loc for loc in scenario.locations}
    
    for entry in time_table:
        section = entry.get("Section") or entry.get("session")
        if isinstance(section, str):
            section = scenario.get_section_by_id(section)
        if not section:
            continue
            
        course = scenario.get_course_by_id(section.course_id)
        if not course:
            violations.append(f"Course for section {section.id} not found")
            continue
            
        required_size = course.required_classroom_size
        if required_size is None:
            continue
            
        room_id = entry.get("Assigned Room")
        if not room_id:
            violations.append(f"Section {section.id} has no room assigned")
            continue
            
        room = location_map.get(room_id)
        if not room:
            violations.append(f"Room {room_id} not found in scenario")
            continue
            
        if room.classroom_capacity is None:
            violations.append(f"Room {room_id} has no classroom capacity defined")
            continue
            
        if room.classroom_capacity < required_size:
            violations.append(
                f"Section {section.id} (course {course.id}) requires room capacity {required_size} "
                f"but assigned room {room_id} has capacity {room.classroom_capacity}"
            )
    
    if violations:
        print("ROOM CAPACITY CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("Room capacity constraints: PASSED")
        return True

def verify_room_types_constraints(config, scenario, time_table):
    from src.domain import RoomType, LabType
    
    violations = []
    
    location_map = {loc.id: loc for loc in scenario.locations}
    
    for entry in time_table:
        section = entry.get("Section") or entry.get("session")
        if isinstance(section, str):
            section = scenario.get_section_by_id(section)
        if not section:
            continue
            
        course = scenario.get_course_by_id(section.course_id)
        if not course:
            violations.append(f"Course for section {section.id} not found")
            continue
            
        required_lab_type = course.required_lab_type
        room_id = entry.get("Assigned Room")
        
        if not room_id:
            violations.append(f"Section {section.id} has no room assigned")
            continue
            
        room = location_map.get(room_id)
        if not room:
            violations.append(f"Room {room_id} not found in scenario")
            continue
        
        if required_lab_type is not None and required_lab_type.upper() != "NONE":
            if room.type != RoomType.LAB and room.type != RoomType.EITHER:
                violations.append(
                    f"Section {section.id} (course {course.id}) requires a lab "
                    f"but assigned room {room_id} is type {room.type}"
                )
            elif (room.lab_type or "").upper() != (required_lab_type or "").upper():
                violations.append(
                    f"Section {section.id} (course {course.id}) requires lab type {required_lab_type} "
                    f"but assigned room {room_id} has lab type {room.lab_type}"
                )
        else:
            if room.type != RoomType.CLASSROOM and room.type != RoomType.EITHER:
                violations.append(
                    f"Section {section.id} (course {course.id}) requires a classroom "
                    f"but assigned room {room_id} is type {room.type}"
                )
    
    if violations:
        print("ROOM TYPE CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("Room type constraints: PASSED")
        return True

def verify_room_double_booking_constraints(config, scenario, time_table):
    violations = []
    
    room_sessions = {}
    
    for entry in time_table:
        section = entry.get("Section") or entry.get("session")
        if isinstance(section, str):
            section = scenario.get_section_by_id(section)
        if not section:
            continue
            
        room_id = entry.get("Assigned Room")
        if not room_id:
            violations.append(f"Section {section.id} has no room assigned")
            continue
        
        day_index = entry.get("Assigned Day")
        slot_index = entry.get("Assigned Slot")
        
        if isinstance(day_index, str):
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_index = days.index(day_index) if day_index in days else day_index
            
        duration = entry.get("Number of Slot", 1)
        term_id = entry.get("Term", "FULL")
        
        for d in range(duration):
            slot_key = (day_index, slot_index + d)
            room_sessions.setdefault(room_id, {}).setdefault(slot_key, []).append((section.id, term_id))
    
    for room_id, slots in room_sessions.items():
        for slot_key, entries in slots.items():
            if len(entries) > 1:
                # Only flag as conflict if any two entries have overlapping terms
                for a in range(len(entries)):
                    for b in range(a + 1, len(entries)):
                        sec_a, term_a = entries[a]
                        sec_b, term_b = entries[b]
                        if scenario.terms_overlap(term_a, term_b):
                            violations.append(
                                f"Room {room_id} has double booking at day {slot_key[0]}, slot {slot_key[1]}: "
                                f"sections {sec_a} ({term_a}) and {sec_b} ({term_b})"
                            )
    
    if violations:
        print("ROOM DOUBLE BOOKING CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("Room double booking constraints: PASSED")
        return True

def verify_daily_distribution_constraints(config, scenario, time_table):
   
    violations = []
    
    course_sessions = {}
    time_table = [e for e in time_table if e.get("Is Start Slot", True)]    
    
    for entry in time_table:
        section = entry.get("Section") or entry.get("session")
        if isinstance(section, str):
            section = scenario.get_section_by_id(section)
        if not section:
            continue
            
        course = scenario.get_course_by_id(section.course_id)
        if not course:
            continue
            
        day_index = entry.get("Assigned Day")
        if isinstance(day_index, str):
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_index = days.index(day_index) if day_index in days else day_index
        
        key = (section.id, course.id)
        if key not in course_sessions:
            course_sessions[key] = {
                'theory_days': [],
                'lab_days': [],
                'course': course
            }
        
        is_lab = course.required_lab_type is not None and course.required_lab_type.upper() != "NONE"
        if is_lab:
            course_sessions[key]['lab_days'].append(day_index)
        else:
            course_sessions[key]['theory_days'].append(day_index)
    
    for key, data in course_sessions.items():
        course = data['course']
        theory_days = data['theory_days']
        lab_days = data['lab_days']
        
        if len(course.theory_durations) > 1:
            theory_day_counts = {}
            for d in theory_days:
                theory_day_counts[d] = theory_day_counts.get(d, 0) + 1
            for day, count in theory_day_counts.items():
                if count > 1:
                    violations.append(
                        f"Course {course.id} (section {key[0]}) has {count} theory sessions on day {day} "
                        f"(has {len(course.theory_durations)} theory sessions total)"
                    )
        
        if len(course.lab_durations) > 1:
            lab_day_counts = {}
            for d in lab_days:
                lab_day_counts[d] = lab_day_counts.get(d, 0) + 1
            for day, count in lab_day_counts.items():
                if count > 1:
                    violations.append(
                        f"Course {course.id} (section {key[0]}) has {count} lab sessions on day {day} "
                        f"(has {len(course.lab_durations)} lab sessions total)"
                    )
    
    if violations:
        print("DAILY DISTRIBUTION CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("Daily distribution constraints: PASSED")
        return True

def verify_every_session_has_room(config, scenario, time_table):
    violations = []

    time_table = [e for e in time_table if e.get("Is Start Slot", True)]    
    assigned_sessions = set()
    for entry in time_table:
        session = entry.get("Session")
        if session:
            assigned_sessions.add(session)
    
    for section in scenario.sections:
        course = scenario.get_course_by_id(section.course_id)
        if not course:
            continue
        
        base_id = section.id
        
        for i, duration in enumerate(course.theory_durations):
            session_id = f"{base_id}_THEORY_{i}"
            if session_id not in assigned_sessions:
                violations.append(f"Session {session_id} (course {course.id}, section {section.id}) has no room or time assigned")
        
        for i, duration in enumerate(course.lab_durations):
            session_id = f"{base_id}_LAB_{i}"
            if session_id not in assigned_sessions:
                violations.append(f"Session {session_id} (course {course.id}, section {section.id}) has no room or time assigned")
    
    if violations:
        print("SESSION HAS ROOM CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("Every session has room: PASSED")
        return True

def _entry_in_term(entry, term, all_terms):
    """Returns True if this timetable entry's term overlaps with the given term."""
    entry_term_id = entry.get("Term", "FULL")
    entry_term = next((t for t in all_terms if t.term_id == entry_term_id), None)
    if entry_term is None:
        return True  # include if term not found
    return entry_term.start_date <= term.end_date and term.start_date <= entry_term.end_date

def generate_pdf_timetables(time_table, scenario, config, output_dir, slot_time_map=None):
    """Generate PDF timetables for cohorts, faculty, and rooms in list format."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    import os
    from collections import defaultdict

    os.makedirs(output_dir, exist_ok=True)
    styles = getSampleStyleSheet()
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    faculty_map = {f.id: f for f in scenario.faculty}

    # Only start slots
    start_only = [e for e in time_table if e.get("Is Start Slot", True)]

    # Styles
    title_style = ParagraphStyle('title', fontSize=14, fontName='Helvetica-Bold',
                                  spaceAfter=6)
    day_style   = ParagraphStyle('day',   fontSize=11, fontName='Helvetica-Bold',
                                  spaceAfter=4, spaceBefore=4)
    cell_style  = ParagraphStyle('cell',  fontSize=8,  leading=10,
                                  alignment=TA_LEFT,   wordWrap='CJK')
    cell_center = ParagraphStyle('cellc', fontSize=8,  leading=10,
                                  alignment=TA_CENTER, wordWrap='CJK')

    def slot_label(slot_num):
        if slot_time_map and slot_num in slot_time_map:
            return f"Slot {slot_num}\n{slot_time_map[slot_num]}"
        return f"Slot {slot_num}"

    def faculty_label(fid):
        fac = faculty_map.get(fid)
        if fac:
            return f"{fac.name} ({fid})"
        return fid

    def session_label(session_str):
        """Convert suffix like '669129__Section_1_THEORY_0' to 'Theory 1'."""
        try:
            parts = session_str.rsplit('_', 2)
            s_type = parts[-2].capitalize()
            s_idx  = str(int(parts[-1]) + 1)  # 0-indexed to 1-indexed
            return f"{s_type} {s_idx}"
        except Exception:
            return session_str

    def section_number(session_str):
        """Extract section number from suffix like '669129__Section_3_THEORY_0'."""
        try:
            # Find 'Section_N' part
            idx = session_str.index('Section_')
            rest = session_str[idx + len('Section_'):]
            return int(rest.split('_')[0])
        except Exception:
            return 0

    def build_table_style(num_rows):
        return TableStyle([
            # Header row
            ('BACKGROUND',   (0, 0), (-1, 0),  colors.HexColor('#2C3E50')),
            ('TEXTCOLOR',    (0, 0), (-1, 0),  colors.white),
            ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0, 0), (-1, 0),  8),
            ('ALIGN',        (0, 0), (-1, 0),  'CENTER'),
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
            ('GRID',         (0, 0), (-1, -1), 0.3, colors.HexColor('#CCCCCC')),
            ('TOPPADDING',   (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
            ('LEFTPADDING',  (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            # Alternating row backgrounds (skip header)
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#F4F6F8')]),
        ])

    def p(text, style=None):
        """Shorthand for Paragraph."""
        return Paragraph(str(text) if text else '', style or cell_style)

    # ------------------------------------------------------------------ #
    #  COHORT timetables                                                   #
    # ------------------------------------------------------------------ #
    print("Generating cohort PDFs...")
    for cohort in scenario.cohorts:
        cid = cohort.id

        # Filter entries for this cohort
        cohort_entries = [
            e for e in start_only
            if 'ALL' in e.get('Eligible Cohorts', [])
            or cid in e.get('Eligible Cohorts', [])
        ]
        if not cohort_entries:
            continue

        # Group by day -> slot -> (course_name, session_type_label) -> [entry]
        by_day = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for e in cohort_entries:
            day  = e.get('Assigned Day')
            slot = e.get('Assigned Slot')
            key  = (e.get('Course name', ''), session_label(e.get('Session', '')))
            by_day[day][slot][key].append(e)

        story = [Paragraph(f"Timetable — {cid}", title_style)]

        col_widths = [2.8*cm, 5.5*cm, 1.5*cm, 1.5*cm, 3.5*cm, 4.2*cm]
        header_row = [p('Time', cell_center), p('Course', cell_center),
                      p('Sec', cell_center),  p('Session', cell_center),
                      p('Room', cell_center),  p('Faculty', cell_center)]

        for day in days:
            if day not in by_day:
                continue
            story.append(PageBreak())
            story.append(Paragraph(day, day_style))

            rows = [header_row]
            for slot in sorted(by_day[day].keys()):
                slot_courses = by_day[day][slot]
                first_in_slot = True
                for (course_name, sess_type) in sorted(slot_courses.keys()):
                    entries = sorted(
                        slot_courses[(course_name, sess_type)],
                        key=lambda e: section_number(e.get('Session', ''))
                    )
                    first_in_course = True
                    for e in entries:
                        time_cell = p(slot_label(slot), cell_center) \
                                    if first_in_slot else p('')
                        course_cell = p(f"<b>{course_name}</b>") \
                                      if first_in_course else p('')
                        sec_num = section_number(e.get('Session', ''))
                        fac_text = '\n'.join(
                            faculty_label(fid)
                            for fid in e.get('faculty_ids', [])
                        )
                        room = e.get('Assigned Room', '')
                        if room in ('NO_ROOM', '—'):
                            room = '(no room)'
                        rows.append([
                            time_cell,
                            course_cell,
                            p(str(sec_num),  cell_center),
                            p(sess_type,     cell_center),
                            p(room),
                            p(fac_text),
                        ])
                        first_in_slot   = False
                        first_in_course = False

            t = Table(rows, colWidths=col_widths)
            t.setStyle(build_table_style(len(rows)))
            story.append(t)
            story.append(Spacer(1, 0.3*cm))

        path = os.path.join(output_dir, f"timetable_cohort_{cid}.pdf")
        doc = SimpleDocTemplate(path, pagesize=A4,
                                leftMargin=1.5*cm, rightMargin=1.5*cm,
                                topMargin=1.5*cm,  bottomMargin=1.5*cm)
        doc.build(story)

    # ------------------------------------------------------------------ #
    #  FACULTY timetables                                                  #
    # ------------------------------------------------------------------ #
    print("Generating faculty PDFs...")
    for fid, fac in faculty_map.items():
        fac_entries = [e for e in start_only if fid in e.get('faculty_ids', [])]
        if not fac_entries:
            continue

        by_day = defaultdict(lambda: defaultdict(list))
        for e in fac_entries:
            by_day[e.get('Assigned Day')][e.get('Assigned Slot')].append(e)

        story = [Paragraph(f"Timetable — {fac.name} ({fid})", title_style)]

        col_widths = [2.8*cm, 5.5*cm, 1.5*cm, 1.8*cm, 3.5*cm, 3.5*cm]
        header_row = [p('Time', cell_center), p('Course', cell_center),
                      p('Sec',  cell_center), p('Session', cell_center),
                      p('Room', cell_center), p('Cohorts', cell_center)]

        for day in days:
            if day not in by_day:
                continue
            story.append(PageBreak())
            story.append(Paragraph(day, day_style))

            rows = [header_row]
            for slot in sorted(by_day[day].keys()):
                for e in sorted(by_day[day][slot],
                                key=lambda x: x.get('Course name', '')):
                    sec_num = section_number(e.get('Session', ''))
                    cohorts = ', '.join(str(c) for c in
                                       e.get('Eligible Cohorts', []))
                    room = e.get('Assigned Room', '')
                    if room in ('NO_ROOM', '—'):
                        room = '(no room)'
                    rows.append([
                        p(slot_label(slot), cell_center),
                        p(f"<b>{e.get('Course name','')}</b>"),
                        p(str(sec_num), cell_center),
                        p(session_label(e.get('Session', '')), cell_center),
                        p(room),
                        p(cohorts),
                    ])

            t = Table(rows, colWidths=col_widths)
            t.setStyle(build_table_style(len(rows)))
            story.append(t)
            story.append(Spacer(1, 0.3*cm))

        path = os.path.join(output_dir, f"timetable_faculty_{fid}.pdf")
        doc = SimpleDocTemplate(path, pagesize=A4,
                                leftMargin=1.5*cm, rightMargin=1.5*cm,
                                topMargin=1.5*cm,  bottomMargin=1.5*cm)
        doc.build(story)

    # ------------------------------------------------------------------ #
    #  ROOM timetables                                                     #
    # ------------------------------------------------------------------ #
    print("Generating room PDFs...")
    room_ids = sorted({
        e['Assigned Room'] for e in start_only
        if e.get('Assigned Room') and e['Assigned Room'] not in ('NO_ROOM', '—')
    })
    for room_id in room_ids:
        room_entries = [e for e in start_only
                        if e.get('Assigned Room') == room_id]
        if not room_entries:
            continue

        by_day = defaultdict(lambda: defaultdict(list))
        for e in room_entries:
            by_day[e.get('Assigned Day')][e.get('Assigned Slot')].append(e)

        story = [Paragraph(f"Timetable — Room {room_id}", title_style)]

        col_widths = [2.8*cm, 5.5*cm, 1.5*cm, 1.8*cm, 4.2*cm, 3.0*cm]
        header_row = [p('Time', cell_center), p('Course', cell_center),
                      p('Sec',  cell_center), p('Session', cell_center),
                      p('Faculty', cell_center), p('Cohorts', cell_center)]

        for day in days:
            if day not in by_day:
                continue
            story.append(PageBreak())
            story.append(Paragraph(day, day_style))

            rows = [header_row]
            for slot in sorted(by_day[day].keys()):
                for e in sorted(by_day[day][slot],
                                key=lambda x: x.get('Course name', '')):
                    sec_num = section_number(e.get('Session', ''))
                    fac_text = '\n'.join(
                        faculty_label(fid)
                        for fid in e.get('faculty_ids', [])
                    )
                    cohorts = ', '.join(str(c) for c in
                                       e.get('Eligible Cohorts', []))
                    rows.append([
                        p(slot_label(slot), cell_center),
                        p(f"<b>{e.get('Course name','')}</b>"),
                        p(str(sec_num), cell_center),
                        p(session_label(e.get('Session', '')), cell_center),
                        p(fac_text),
                        p(cohorts),
                    ])

            t = Table(rows, colWidths=col_widths)
            t.setStyle(build_table_style(len(rows)))
            story.append(t)
            story.append(Spacer(1, 0.3*cm))

        safe_id = room_id.replace('/', '_').replace(' ', '_')
        path = os.path.join(output_dir, f"timetable_room_{safe_id}.pdf")
        doc = SimpleDocTemplate(path, pagesize=A4,
                                leftMargin=1.5*cm, rightMargin=1.5*cm,
                                topMargin=1.5*cm,  bottomMargin=1.5*cm)
        doc.build(story)

    # ------------------------------------------------------------------ #
    #  FULL and PER-TERM timetables (list format, all sections)           #
    # ------------------------------------------------------------------ #
    def build_full_story(entries, title_text):
        by_day = defaultdict(lambda: defaultdict(list))
        for e in entries:
            by_day[e.get('Assigned Day')][e.get('Assigned Slot')].append(e)

        story = [Paragraph(title_text, title_style)]
        col_widths = [2.8*cm, 5.0*cm, 1.5*cm, 1.8*cm, 3.5*cm, 3.5*cm, 1.8*cm]
        header_row = [p('Time', cell_center), p('Course', cell_center),
                      p('Sec',  cell_center), p('Session', cell_center),
                      p('Room', cell_center), p('Faculty', cell_center),
                      p('Term', cell_center)]

        for day in days:
            if day not in by_day:
                continue
            story.append(PageBreak())
            story.append(Paragraph(day, day_style))
            rows = [header_row]
            for slot in sorted(by_day[day].keys()):
                for e in sorted(by_day[day][slot],
                                key=lambda x: x.get('Course name', '')):
                    sec_num = section_number(e.get('Session', ''))
                    fac_text = '\n'.join(
                        faculty_label(fid)
                        for fid in e.get('faculty_ids', [])
                    )
                    room = e.get('Assigned Room', '')
                    if room in ('NO_ROOM', '—'):
                        room = '(no room)'
                    rows.append([
                        p(slot_label(slot), cell_center),
                        p(f"<b>{e.get('Course name','')}</b>"),
                        p(str(sec_num), cell_center),
                        p(session_label(e.get('Session', '')), cell_center),
                        p(room),
                        p(fac_text),
                        p(e.get('Term', 'FULL'), cell_center),
                    ])
            t = Table(rows, colWidths=col_widths)
            t.setStyle(build_table_style(len(rows)))
            story.append(t)
            story.append(Spacer(1, 0.3*cm))
        return story

    print("Generating full timetable PDF...")
    path = os.path.join(output_dir, "timetable_FULL.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm,  bottomMargin=1.5*cm)
    doc.build(build_full_story(start_only, "Timetable — Full Term"))

    print("Generating term PDFs...")
    for term in scenario.terms:
        term_entries = [e for e in start_only
                        if _entry_in_term(e, term, scenario.terms)]
        if not term_entries:
            continue
        path = os.path.join(output_dir, f"timetable_term_{term.term_id}.pdf")
        doc = SimpleDocTemplate(path, pagesize=A4,
                                leftMargin=1.5*cm, rightMargin=1.5*cm,
                                topMargin=1.5*cm,  bottomMargin=1.5*cm)
        doc.build(build_full_story(term_entries,
                                   f"Timetable — {term.term_id}"))

    print(f"✅ PDFs written to {output_dir}/")

def _cohort_terms(cohort_id, time_table, scenario):
    """
    Returns the ordered list of Term objects that are relevant for a cohort.
    A term is relevant if the cohort has at least one session in it.
    FULL-term entries contribute to every term's skeleton so 'FULL' is
    included as a synthetic term if any full-term entries exist for the cohort.
    Returned list is sorted by term start_date.
    """
    from datetime import date as date_type
    cohort_id_upper = cohort_id.upper()
    cohort_entries = [
        e for e in time_table
        if e.get("Is Start Slot", True)
        and ('ALL' in e.get('Eligible Cohorts', [])
             or cohort_id_upper in [c.upper() for c in e.get('Eligible Cohorts', [])])
    ]
    if not cohort_entries:
        return []

    # Collect term_ids actually used by this cohort
    used_term_ids = set(e.get('Term', 'FULL') for e in cohort_entries)

    # Build the relevant Term objects
    term_map = {t.term_id: t for t in scenario.terms}
    relevant = []
    has_full = False
    for tid in used_term_ids:
        if tid == 'FULL' or tid not in term_map:
            has_full = True
        else:
            relevant.append(term_map[tid])

    # Add a synthetic FULL term spanning all dates if needed
    if has_full:
        all_starts = [t.start_date for t in scenario.terms]
        all_ends   = [t.end_date   for t in scenario.terms]
        from src.domain import Term
        full_term = Term(
            term_id='FULL',
            start_date=min(all_starts) if all_starts else date_type(2026,1,1),
            end_date=  max(all_ends)   if all_ends   else date_type(2026,12,31),
        )
        relevant.append(full_term)

    # Sort by start_date so FULL (earliest) comes first
    relevant.sort(key=lambda t: t.start_date)
    return relevant


def generate_cohort_excel_sheets(cohort_id, time_table, scenario, config, writer):
    """
    Write skeleton and timetable sheets for one cohort into an ExcelWriter.
    Produces one skeleton per relevant term (stacked with term label) and
    one timetable section per relevant term (stacked with term label).
    Full-term entries appear in every term's section.
    """
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    cohort_id_upper = cohort_id.upper()

    # All entries for this cohort (start slots only for skeleton/timetable display)
    cohort_entries_all = [
        e for e in time_table
        #if e.get("Is Start Slot", True)
        if ('ALL' in e.get('Eligible Cohorts', [])
             or cohort_id_upper in [c.upper() for c in e.get('Eligible Cohorts', [])])
    ]
    if not cohort_entries_all:
        return

    relevant_terms = _cohort_terms(cohort_id, time_table, scenario)
    if not relevant_terms:
        return

    # ---- SKELETON SHEET ----
    # One skeleton grid per term, stacked vertically with a label row between them
    skeleton_rows = []
    for term in relevant_terms:
        # Filter entries: include if entry's term overlaps with this term
        term_entries = [
            e for e in cohort_entries_all
            if _entry_in_term(e, term, scenario.terms)
        ]
        # Label row
        skeleton_rows.append({col: '' for col in ['Day'] +
                               [f'Slot {i}' for i in range(config.slots_per_day)]})
        # print("SKELETON ROW ", skeleton_rows)
        # print("SKELETON ROW -1 ", skeleton_rows[-1])
        # print("SKELETON ROW -1 Day", skeleton_rows[-1]['Day'])
        # print("TERM ID ", term.term_id)
        skeleton_rows[-1]['Day'] = f"{term.term_id}".upper()

        # Generate skeleton for this term's entries
        skeleton_df = generate_skeleton(term_entries, config)
        for _, row in skeleton_df.iterrows():
            skeleton_rows.append(row.to_dict())

        # Blank separator row
        skeleton_rows.append({col: '' for col in ['Day'] +
                               [f'Slot {i}' for i in range(config.slots_per_day)]})

    skeleton_sheet_df = pd.DataFrame(skeleton_rows)
    sheet_name = f"Skel_{cohort_id}"[:31]
    skeleton_sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)

    # ---- TIMETABLE SHEET ----
    # Columns to include (subset relevant for a cohort view)
    tt_cols = ['Course name', 'Category', 'Faculty', 'Assigned Day',
               'Assigned Slot', 'Session', 'Assigned Room',
               'Number of Slot', 'Term']

    timetable_rows = []
    for term in relevant_terms:
        term_entries = [
            e for e in cohort_entries_all
            if _entry_in_term(e, term, scenario.terms)
        ]
        # Sort by day then slot
        term_entries_sorted = sorted(
            term_entries,
            key=lambda e: (days.index(e.get('Assigned Day', 'Mon'))
                           if e.get('Assigned Day') in days else 0,
                           e.get('Assigned Slot', 0))
        )
        # Label row — use first column only
        label_row = {col: '' for col in tt_cols}
        label_row['Course name'] = f"{term.term_id}".upper()
        timetable_rows.append(label_row)

        for e in term_entries_sorted:
            #print(e)
            row = {col: e.get(col, '') for col in tt_cols}
            # Eligible Cohorts is a list — convert to string
            if isinstance(row.get('Eligible Cohorts'), list):
                row['Eligible Cohorts'] = ', '.join(row['Eligible Cohorts'])
            timetable_rows.append(row)

        # Blank separator
        timetable_rows.append({col: '' for col in tt_cols})

    tt_sheet_df = pd.DataFrame(timetable_rows, columns=tt_cols)
    tt_sheet_name = f"TT_{cohort_id}"[:31]
    tt_sheet_df.to_excel(writer, sheet_name=tt_sheet_name, index=False)

def generate_skeleton(time_table, config):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    slots_per_day = config.slots_per_day
    
    grid = {day: {slot: [] for slot in range(slots_per_day)} for day in range(len(days))}
    
    for entry in time_table:
        day_str = entry.get("Assigned Day")
        if isinstance(day_str, str):
            day_index = days.index(day_str) if day_str in days else day_str
        else:
            day_index = day_str
            
        if isinstance(day_index, int) and 0 <= day_index < len(days):
            slot_index = entry.get("Assigned Slot", 0)
            duration = entry.get("Number of Slot", 1)
            category = entry.get("Category", "UNKNOWN")
            
            if 0 <= slot_index < slots_per_day:
                if category not in grid[day_index][slot_index]:
                    grid[day_index][slot_index].append(category)
    
    skeleton_data = []
    for day_idx in range(len(days)):
        row = {"Day": days[day_idx]}
        for slot_idx in range(slots_per_day):
            categories = grid[day_idx][slot_idx]
            row[f"Slot {slot_idx}"] = ", ".join(sorted(categories)) if categories else ""
        skeleton_data.append(row)
    
    df = pd.DataFrame(skeleton_data)
    
    # print("\n=== TIMETABLE SKELETON ===")
    # print(df.to_string(index=False))
    
    return df


def generate_cohort_skeletons(time_table, config, scenario):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    slots_per_day = config.slots_per_day
    
    category_map = {c.id: c for c in scenario.course_categories}
    
    cohort_ids = [c.id for c in scenario.cohorts]
    #print(f"DEBUG: Cohorts in scenario: {cohort_ids[:10]}...")
    
    #print("DEBUG: Courses with COMPLETE category in time_table:")
    for entry in time_table:
        cat = entry.get("Category", "UNKNOWN")
        cat_obj = category_map.get(cat)
        # if cat_obj and cat_obj.choice_type == 'COMPLETE':
        #     print(f"  Course: {entry.get('Course name')}, Category: {cat}, Eligible Cohorts: {entry.get('Eligible Cohorts')}")
    
    cohort_timetables = {}
    
    for cohort in scenario.cohorts:
        cohort_id = cohort.id
        grid = {day: {slot: set() for slot in range(slots_per_day)} for day in range(len(days))}
        
        for entry in time_table:
            duration = entry['duration']
            for d in range(duration):
                #print(d)       
                eligible_cohorts = entry.get("Eligible Cohorts", [])
                if not eligible_cohorts:
                    continue
                if 'ALL' not in eligible_cohorts and cohort_id not in eligible_cohorts:
                    continue
                
                day_str = entry.get("Assigned Day")
                if isinstance(day_str, str):
                    day_index = days.index(day_str) if day_str in days else day_str
                else:
                    day_index = day_str
                
                if isinstance(day_index, int) and 0 <= day_index < len(days):
                    if d > 0:
                        print("!!!")
                    slot_index = entry.get("Assigned Slot", 0)
                    duration = entry.get("Number of Slot", 1)
                    category = entry.get("Category", "UNKNOWN")
                    course_name = entry.get("Course name", "")
                    
                    cat_obj = category_map.get(category)
                    #if cat_obj and cat_obj.choice_type == 'COMPLETE':
                    display = f"({category})"
                    # else:
                    #     display = f"{course_name} ({category})"
                    
                    if 0 <= slot_index < slots_per_day:
                        if d > 0:
                            print("!!!!!!")                        
                        if category not in grid[day_index][slot_index]:
                            grid[day_index][slot_index].add(display)                        
        
        timetable_data = []
        for day_idx in range(len(days)):
            row = {"Day": days[day_idx]}
            for slot_idx in range(slots_per_day):
                entries = sorted(grid[day_idx][slot_idx])
                row[f"Slot {slot_idx}"] = ", ".join(entries) if entries else ""
            timetable_data.append(row)
        
        cohort_timetables[cohort_id] = pd.DataFrame(timetable_data)
    
    return cohort_timetables

def verify_no_cohort_conflicts_constraints(config, scenario, time_table):
    from src.domain import CourseCategory
    
    violations = []
    
    category_map = {c.id: c for c in scenario.course_categories}
    section_map = {s.id: s for s in scenario.sections}
    
    slot_courses = {}
    for entry in time_table:
        section = entry.get("Section") or entry.get("session")
        if isinstance(section, str):
            section = section_map.get(section)
        if not section:
            continue
        
        day_index = entry.get("Assigned Day")
        slot_index = entry.get("Assigned Slot")
        
        if isinstance(day_index, str):
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_index = days.index(day_index) if day_index in days else day_index
        
        slot_key = (day_index, slot_index)
        
        if slot_key not in slot_courses:
            slot_courses[slot_key] = []
        
        category = category_map.get(section.category_id)
        slot_courses[slot_key].append({
            'section': section,
            'category': category,
            'cohorts': section.eligible_cohorts,
            'term_id': entry.get("Term", "FULL")
        })
    
    for slot_key, courses in slot_courses.items():
        courses_by_category = {}
        for course in courses:
            cat_id = course['section'].category_id
            if cat_id not in courses_by_category:
                courses_by_category[cat_id] = []
            courses_by_category[cat_id].append(course)
        
        for cat_id, cat_courses in courses_by_category.items():
            category = category_map.get(cat_id)
            if not category:
                continue
            
            if category.choice_type == 'COMPLETE':
                continue
            
            if category.choice_count <= 1:
                for i, c1 in enumerate(cat_courses):
                    for c2 in cat_courses[i+1:]:
                        if not scenario.terms_overlap(c1['term_id'], c2['term_id']):
                            continue
                        shared_cohorts = set(c1['cohorts']) & set(c2['cohorts'])
                        if shared_cohorts:
                            violations.append(
                                f"Cohort conflict at day {slot_key[0]}, slot {slot_key[1]}: "
                                f"Course {c1['section'].course_id} (section {c1['section'].id}) and "
                                f"Course {c2['section'].course_id} (section {c2['section'].id}) "
                                f"share cohorts {shared_cohorts} but category {cat_id} has choice_count={category.choice_count}"
                            )
            else:
                if len(cat_courses) > category.choice_count:
                    violations.append(
                        f"Category {cat_id} choice count exceeded at day {slot_key[0]}, slot {slot_key[1]}: "
                        f"{len(cat_courses)} courses scheduled but choice_count={category.choice_count}. "
                        f"Courses: {[c['section'].id for c in cat_courses]}"
                    )
    
    if violations:
        print("COHORT CONFLICT CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        return False
    else:
        print("No cohort conflicts: PASSED")
        return True
    
# def verify_no_cohort_conflicts_constraints(config, scenario, time_table):


          
    #     exporter = ResultExporter(
    #         scenario, 
    #         engine, 
    #         solver.section_vars, 
    #         solver.cohort_split_vars
    #     )
        
    #     # This will print the grid/table to your console
    #     exporter.generate_summary()
    #     exporter.export_to_excel(output_file="output/tt_by_course.xlsx")
        
    #     # Optional: Print the 'cost' of the solution (lower is better)
    #     print(f"\nFinal Penalty Score: {engine.ObjectiveValue()}")
    #     if engine.ObjectiveValue() > 100000:
    #         print("WARNING: High penalty detected. Look for 'CONFLICT' or 'Split' in the results.")
            
    # elif status == cp_model.INFEASIBLE:
    #     print("CRITICAL ERROR: The model is fundamentally infeasible.")
    #     solver.get_infeasible_reasons()
    # else:
    #     print("Solver timed out or failed without a status.")
if __name__ == "__main__":
    main()
