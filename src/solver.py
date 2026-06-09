from ortools.sat.python import cp_model
from collections import defaultdict
from .domain import TimetableScenario
import sys

class SolutionProgressTracker(cp_model.CpSolverSolutionCallback):
    
    def __init__(self, session_vars, hint_filepath):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._session_vars = session_vars
        self._hint_filepath = hint_filepath
        self._solutions = []
        self._start_time = None
        self._best_objective = float('inf')

    def on_solution_callback(self):
        import time, json
        if self._start_time is None:
            self._start_time = time.time()
        elapsed = time.time() - self._start_time
        obj = self.ObjectiveValue()
        self._solutions.append((elapsed, obj))
        self._best_objective = obj
        print(f"  [Tracker] t={elapsed:.0f}s objective={obj:.0f}")
        if self._hint_filepath is not None:
            hints = {suffix: self.Value(data["start"])
                     for suffix, data in self._session_vars.items()}
            with open(self._hint_filepath, 'w') as f:
                json.dump(hints, f)

    def improvement_rate(self, window_seconds=300):
        if self._start_time is None:
            return float('inf')
        import time
        now = time.time() - self._start_time
        recent = [(t, o) for t, o in self._solutions if t >= now - window_seconds]
        if len(recent) < 2:
            return float('inf')
        return (recent[0][1] - recent[-1][1]) / (window_seconds / 60)

    def is_stalled(self, window_seconds=300, min_improvement_per_minute=50):
        return self.improvement_rate(window_seconds) < min_improvement_per_minute

    def summary(self):
        if not self._solutions:
            return "No solutions found"
        return (f"Solutions: {len(self._solutions)}, "
                f"Best: {self._best_objective:.0f}, "
                f"Rate: {self.improvement_rate():.1f}/min")
    
class TimetableSolver:
    
    def __init__(self, scenario: TimetableScenario,relax_on_failure: bool = True):
        self.scenario = scenario
        self.model = cp_model.CpModel()
        self.penalties = []
        self.conflicts = [] # To store the boolean variables tracking failures        
        
        # Helper variables
        self.num_days = scenario.config.days_per_week
        self.slots_per_day = scenario.config.slots_per_day
        self.total_slots = self.num_days * self.slots_per_day

       
        # Storage for solver variables
        self.session_vars = {} # Stores (start, end, interval, room) for each section
        self.room_intervals = {} # keyed by (loc.id, term_id)
        self.faculty_map = {f.id: f for f in scenario.faculty}
        self.faculty_intervals = {}  # keyed by (faculty_id, term_id)
        self.cohort_intervals = {c.id: [] for c in scenario.cohorts}
        _all_cohorts = [c.id for c in scenario.cohorts if c.id.lower() != 'all']
        self.all_cohorts = set(_all_cohorts)
        self.session_start_lits = {}
        
    def _terms_overlap(self, term_id_1: str, term_id_2: str) -> bool:
        """Returns True if two term IDs overlap in calendar time."""
        return self.scenario.terms_overlap(term_id_1, term_id_2)

    def _get_feasible_locations(self, course, s_type):
        """Filter locations based on Pydantic attributes"""
        feasible = []
        for loc in self.scenario.locations:
            if s_type == "LAB":
                if loc.type in ["LAB", "EITHER"] and loc.lab_type == course.required_lab_type:
                    feasible.append(loc)
            else: # THEORY
                if loc.type in ["CLASSROOM", "EITHER"]:
                    if loc.classroom_capacity >= (course.required_classroom_size or 0):
                        feasible.append(loc)
        return feasible
    
    def get_allowed_start_indices(self, section, duration):
        """
        Calculates the valid 'start' indices for a session by filtering 
        against all hard constraints.
        
        Combines all time-based rules:
        1. Faculty availability
        2. Lunch slots
        3. Day boundary spillover
        4. Meeting slots
        5. Category maps        
        """
        global_allowed_starts = [1,2,3,4,7,8,9,10,13,14,15,16, 19,20,21,22, 25,26,27,28]
        course_cat_id = section.category.lower().strip()
        course_cat = self.scenario.get_course_category_by_id(course_cat_id)

        if section.allowed_slots:
            allowed_slots = section.allowed_slots
        elif course_cat.allowed_slots:
            allowed_slots = course_cat.allowed_slots
        else:
            allowed_slots = global_allowed_starts
        

        # Pre-process category_slots for faster lookup: (day, slot) -> [categories]
        # We use .get() to handle slots that might not be in the dictionary
        cat_restrictions = {
            (ts.day_index, ts.slot_index): cats 
            for ts, cats in self.scenario.config.category_slots.items()
        }
        # print(cat_restrictions)

        allowed_starts = []
        slots_per_day = 6

        faculty_map = {f.id: f for f in self.scenario.faculty}
        faculty_ok = None
        if course_cat and course_cat.choice_type.upper() != 'VIRTUAL_OPEN':
            for fid in section.faculty_ids:
                fac = faculty_map[fid]
                fac_slots = {(s.day_index * slots_per_day + s.slot_index) for s in fac.available_slots}
                faculty_ok = fac_slots if faculty_ok is None else faculty_ok & fac_slots
        
        # VIRTUAL_OPEN has no faculty — treat all slots as faculty-available
        if course_cat and course_cat.choice_type.upper() == 'VIRTUAL_OPEN':
            faculty_ok = set(range(self.total_slots))
        elif faculty_ok is None:
            faculty_ok = set()

        course = self.scenario.get_course_by_id(section.course_id)
        all_program_ids = list(course.program_ids) + ["GLOBAL"]

        for current_start in allowed_slots:
            start_day = current_start // slots_per_day
            current_end = current_start + duration -1
            end_day = current_end // slots_per_day
            if (start_day != end_day) or (start_day == end_day and current_end not in allowed_slots):
                # if course_cat_id.upper().strip() == "CRX":
                #     print("Skipping ", current_start, current_end, start_day, end_day)
                continue
            
            # 2. Sequential Check for all slots this session will occupy
            all_slots_ok = True
            for d in range(duration):
                check_idx = current_start + d
                d_idx = check_idx // slots_per_day
                s_idx = check_idx % slots_per_day
                
                # --- EXISTING CHECKS (Faculty, Lunch, etc.) ---
                if check_idx not in faculty_ok:
                    all_slots_ok = False
                    failure_reason = f"Faculty Busy at Day {d_idx} Slot {s_idx}, {section.id}"
                    #print(failure_reason)
                    break

                if s_idx in self.scenario.config.lunch_slots:
                    all_slots_ok = False
                    failure_reason = f"Lunch Conflict at Slot {s_idx}"
                    #print(failure_reason)
                    #print("Lunch restriction failed")
                    break

            # print(all_slots_ok)
            if all_slots_ok:
                #print("APPENDING!!")
                allowed_starts.append(current_start)

        return allowed_starts

    def add_meeting_slot_penalties(self, default_violation_penalty=100000, global_violation_penalty=200000):
        print("=== Adding meeting slot penalties ===")
        self.meeting_violations = []
        
        for suffix, data in self.session_vars.items():
            section = data["section"]
            # if section.course_id == "669402":
            #     print(suffix)
            course = self.scenario.get_course_by_id(section.course_id)
            all_prog_ids = [p.upper() for p in (course.program_ids or [])] + ["GLOBAL"]
            
            # Build blocked slots for this session
            blocked = set()
            global_blocked = set()
            for prog_id in all_prog_ids:
                program = self.scenario.get_program_by_id(prog_id)
                if program:
                    if prog_id == "GLOBAL":
                        global_blocked.update(program.meeting_slots)
                    else:   
                        blocked.update(program.meeting_slots)
            
            if not blocked:
                continue
            # if section.course_id == "669402":
            #     print("Blocked ", blocked)
            # For each allowed start that would occupy a blocked slot, add penalty
            lits = self.session_start_lits[suffix]
            for st, lit in lits.items():
                occupies_blocked = False
                occupies_global_blocked = False
                for offset in range(data["duration"]):
                    if st + offset in blocked or st + offset in global_blocked:
                        if st + offset in global_blocked:
                            occupies_global_blocked = True
                        else:
                            occupies_blocked = True
                        break
                # if section.course_id == "669402":
                #     print("Start ", st, "Duration ", data["duration"], "occupies_blocked ", occupies_blocked)
                if occupies_blocked or occupies_global_blocked:
                    if occupies_global_blocked:
                        self.penalties.append(lit * global_violation_penalty)
                    else:
                        self.penalties.append(lit * default_violation_penalty)
                
                    self.meeting_violations.append({
                        "suffix": suffix,
                        "slot": st,
                        "var": lit,          # reuse the existing lit directly
                        "section": section
                    })

    def create_variables(self):
        """
        This function goes through every section of every course and sets up the decisions the 
        solver needs to make — essentially creating a blank timetable grid where each session 
        is an open question waiting to be answered.
        """
        for section in self.scenario.sections:
            course = self.scenario.get_course_by_id(section.course_id)

            # For each section, it first checks whether the category is one the solver handles 
            # (NONE, CONSTRAINED, GROUPED, COMPLETE). If not, it skips it entirely.
            category = self.scenario.get_course_category_by_id(section.category_id)
            if category.choice_type not in  ["COMPLETE", "NONE", "CONSTRAINED", "GROUPED", "VIRTUAL_STAFFED", "VIRTUAL_OPEN"]:
                continue

            #For each session that needs scheduling — whether it's a theory session or a lab session
            configs = [("THEORY", course.theory_durations), ("LAB", course.lab_durations)]
            for s_type, durations in configs:
                for i, duration in enumerate(durations):
                    # Create suffix for every slot that each session type occupies for every entry in the sections sheet
                    # e.g 669146_THEORY_0 and 669146_THEORY_1 if its a 2 slot session
                    suffix = f"{section.id}_{s_type}_{i}" 
                    
                    # --- NEW DOMAIN LOGIC ---
                    # Get the list of all possible slots that this session can start at
                    #Works out when the session CAN happen
                    # Calculate every possible time slot where this session could legally start, 
                    # taking into account the faculty member's availability, lunch breaks, day boundaries, 
                    # and how long the session runs. For example, a 2-slot session can't start in the 
                    # last slot of a day because it would spill into the next day. This gives a shortlist 
                    # of valid start times. 
                    valid_starts = self.get_allowed_start_indices(section, duration)
                    #print(course.id, valid_starts)
                    
                    # If no valid start times exist, it immediately raises an error — 
                    # the data has a problem that must be fixed before solving.
                    if not valid_starts:
                        raise ValueError(f"No valid time slots found for session {suffix}. Check faculty availability.")


                    # For each session, it creates two open questions for the solver: 
                    # "what time does this session start?" (restricted to only the valid times calculated above) 
                    # and "what time does it end?" (which is simply start + duration). 
                    # These two are always kept in sync.

                    # Define 'start' using the pre-filtered domain
                    start = self.model.NewIntVarFromDomain(
                        cp_model.Domain.FromValues(valid_starts), 
                        f"start_{suffix}"
                    )
                    
                    # Define 'end' using the pre-filtered domain
                    end = self.model.NewIntVar(0, self.total_slots, f"end_{suffix}")

                    # Link start + duration = end
                    self.model.Add(end == start + duration)
                    
                    # --- END DOMAIN LOGIC ---

                    master_interval = self.model.NewIntervalVar(start, duration, end, f"master_{suffix}")

                    # Room Variables (Optional Intervals) remain the same...
                    # It looks at all the rooms that are suitable for this session — 
                    # the right type (classroom vs lab), the right size, and the right lab 
                    # equipment if needed. For each suitable room, it creates a yes/no 
                    # question: "is this session in this room?" It also registers the session's 
                    # time block with each candidate room so the solver knows to prevent two 
                    # sessions from being in the same room at the same time.
                    is_virtual = category.choice_type.upper() in (
                        'VIRTUAL_STAFFED', 'VIRTUAL_OPEN')

                    if is_virtual:
                        dummy_pres = self.model.NewBoolVar(f"pres_{suffix}_NOROOM")
                        self.model.Add(dummy_pres == 1)
                        presence_literals = [dummy_pres]
                        presence_map = {"NO_ROOM": dummy_pres}
                    else:                    
                        presence_literals = []
                        feasible_locs = self._get_feasible_locations(course, s_type)
                        
                        presence_map = {}
                        for loc in feasible_locs:
                            pres = self.model.NewBoolVar(f"pres_{suffix}_{loc.id}")
                            presence_literals.append(pres)
                            presence_map[loc.id] = pres # For extraction
                            
                            opt_interval = self.model.NewOptionalIntervalVar(
                                start, duration, end, pres, f"opt_room_int_{suffix}_{loc.id}"
                            )
                            room_key = (loc.id, section.term_id)
                            if room_key not in self.room_intervals:
                                self.room_intervals[room_key] = []
                            self.room_intervals[room_key].append(opt_interval)
                    
                    # Finally, all of this information — the section, 
                    # the possible start times, the duration, the room 
                    # candidates, and the session type — is stored together so 
                    # the rest of the solver can apply the timetabling rules on top of it.
                    self.session_vars[suffix] = {
                        "section": section,
                        "start": start,
                        "end": end,
                        "master_interval": master_interval,
                        "presences": presence_literals,
                        "duration": duration,
                        "presence_map": presence_map,
                        "type": s_type,
                        "allowed_starts_list": valid_starts,
                        "term_id": section.term_id
                    }
                    if category.choice_type.upper() != 'VIRTUAL_OPEN':
                        # VIRTUAL_OPEN has no faculty so skip
                        # Add to Faculty tracker for NoOverlap constraint
                        for fid in section.faculty_ids:
                            fac_key = (fid, section.term_id)
                            if fac_key not in self.faculty_intervals:
                                self.faculty_intervals[fac_key] = []
                            self.faculty_intervals[fac_key].append(master_interval)

    def add_daily_distribution_constraints(self, consecutive_day_penalty = 5000):
        print("--- Applying Daily Distribution (Max one session per day per section) ---")
        
        section_to_sessions = {}
        for suffix, data in self.session_vars.items():
            # Clean section key extraction
            #print("SUFFIX - ", suffix)
            parts = suffix.split('_')

            # Use below if we are ok with some lab and theory being on the same day
            #section_key = "_".join(parts[:-1]) 

            # Use below if we dont want all labs and theory session spread out over days
            section_key = data["section"].id
            #print("SECTION - ", section_key)

            
            if section_key not in section_to_sessions:
                section_to_sessions[section_key] = []
            section_to_sessions[section_key].append(data)

        for section_key, sessions in section_to_sessions.items():
            if len(sessions) <= 1:
                continue
            # Group into clusters where all sessions overlap in time with at least one other
            # Sessions from non-overlapping terms can share days
            overlapping_groups = []
            for sess in sessions:
                placed = False
                for group in overlapping_groups:
                    if any(self._terms_overlap(sess["term_id"], s["term_id"]) for s in group):
                        group.append(sess)
                        placed = True
                        break
                if not placed:
                    overlapping_groups.append([sess])

            for group_idx, group in enumerate(overlapping_groups):
                if len(group) <= 1:
                    continue
                if len(group) > self.num_days:
                    print(f"  ⚠️ WARNING: Section {section_key} has {len(group)} overlapping sessions but only {self.num_days} days. Relaxing constraint.")
                    continue
                day_vars = []
                for i, session_data in enumerate(group):
                    day_var = self.model.NewIntVar(0, self.num_days - 1, f'day_{section_key}_{session_data["term_id"]}_{i}')
                    self.model.AddDivisionEquality(day_var, session_data["start"], self.slots_per_day)
                    day_vars.append(day_var)
                self.model.AddAllDifferent(day_vars)
                # -----------------------------------------------------------------
                # SOFT CONSTRAINT: Prefer at least a 1-day gap between sessions
                # -----------------------------------------------------------------
                for i in range(len(day_vars)):
                    for j in range(i + 1, len(day_vars)):
                        # 1. Calculate the raw difference between the two days
                        diff_var = self.model.NewIntVar(-(self.num_days - 1), self.num_days - 1, f'diff_{section_key}_{group_idx}_{i}_{j}')
                        self.model.Add(diff_var == day_vars[i] - day_vars[j])
                        
                        # 2. Get the absolute difference (e.g., |Mon(0) - Tue(1)| = 1)
                        # We set the lower bound to 1 because AddAllDifferent guarantees they are never on the same day (0)
                        abs_diff_var = self.model.NewIntVar(1, self.num_days - 1, f'abs_diff_{section_key}_{group_idx}_{i}_{j}')
                        self.model.AddAbsEquality(abs_diff_var, diff_var)
                        
                        # 3. Create a boolean flag that is True ONLY IF the days are exactly consecutive
                        is_consec = self.model.NewBoolVar(f'is_consec_{section_key}_{group_idx}_{i}_{j}')
                        
                        # Link the boolean to the condition: abs_diff_var == 1
                        self.model.Add(abs_diff_var == 1).OnlyEnforceIf(is_consec)
                        self.model.Add(abs_diff_var > 1).OnlyEnforceIf(is_consec.Not())
                        
                        # 4. Add the penalty to the objective function
                        self.penalties.append(is_consec * consecutive_day_penalty)


    def add_faculty_rest_soft_constraint(self, penalty_weight=5000):
        """
        Soft constraint: Penalize back-to-back sessions for the same faculty on the same day.
        A back-to-back occurs if Session 1 ends at slot T, and Session 2 starts at slot T.
        """
        print("--- Applying Soft Constraint: Faculty Rest (No back-to-back on same day) ---")

        # 1. Group sessions by faculty
        faculty_sessions = {f_id: [] for f_id in self.faculty_map.keys()}
        for suffix, data in self.session_vars.items():
            for f_id in data["section"].faculty_ids:
                faculty_sessions[f_id].append((suffix, data))

        # 2. For each faculty, check pairs of sessions
        for f_id, sessions in faculty_sessions.items():
            n = len(sessions)
            if n < 2:
                continue

            for i in range(n):
                suffix1, s1 = sessions[i]
                for j in range(i + 1, n):
                    suffix2, s2 = sessions[j]

                    # If they don't overlap in the calendar term, they can't be back-to-back
                    if not self._terms_overlap(s1["term_id"], s2["term_id"]):
                        continue

                    lits1 = self.session_start_lits[suffix1]
                    lits2 = self.session_start_lits[suffix2]

                    dur1 = s1["duration"]
                    dur2 = s2["duration"]

                    # --- Check Direction A: S1 ends exactly when S2 starts ---
                    for st1, lit1 in lits1.items():
                        end1 = st1 + dur1
                        if st1 // self.slots_per_day != end1 // self.slots_per_day:
                            continue
                        #if end1 % self.slots_per_day != 0 and end1 in lits2:
                        if end1 in lits2:
                            lit2 = lits2[end1]
                            # Create a boolean that is 1 if both lit1 and lit2 are true
                            b2b_var = self.model.NewBoolVar(f'b2b_{f_id}_{suffix1}_{suffix2}_{st1}_{end1}')
                            
                            # Logic: If lit1 == 1 AND lit2 == 1 -> b2b_var must be 1
                            self.model.AddBoolOr([lit1.Not(), lit2.Not(), b2b_var])
                            
                            # Add the penalty
                            self.penalties.append(b2b_var * penalty_weight)
                            self.conflicts.append({
                                "type": "FACULTY_B2B",
                                "first_start": st1,
                                "faculty_id": f_id,
                                "first_suffix": suffix1,
                                "second_suffix": suffix2,
                                "var": b2b_var
                            })

                    # --- Check Direction B: S2 ends exactly when S1 starts ---
                    for st2, lit2 in lits2.items():
                        end2 = st2 + dur2
                        #if end2 % self.slots_per_day != 0 and end2 in lits1:
                        if st2 // self.slots_per_day != end2 // self.slots_per_day:
                            continue                        
                        if  end2 in lits1:                            
                            lit1 = lits1[end2]
                            b2b_var = self.model.NewBoolVar(f'b2b_{f_id}_{suffix2}_{suffix1}_{st2}_{end2}')
                            
                            self.model.AddBoolOr([lit2.Not(), lit1.Not(), b2b_var])
                            
                            self.penalties.append(b2b_var * penalty_weight)
                            self.conflicts.append({
                                "type": "FACULTY_B2B",
                                "first_start": st2,
                                "faculty_id": f_id,
                                "first_suffix": suffix2,
                                "second_suffix": suffix1,
                                "var": b2b_var
                            })

    def add_faculty_constraints(self):
        # Make sure that none of the faculty's session intervals overlap - basically
        # ensuring that they are not double booked
        for f_id, intervals in self.faculty_intervals.items():
            if len(intervals) > 1:
                self.model.AddNoOverlap(intervals)

    def _debug_hard_wall(self, cohort_to_conflict_groups):
        """
        Pre-solve diagnostic: detects Hard Wall infeasibility by checking
        whether overlapping units for a cohort can all fit into distinct slots,
        taking faculty availability into account via allowed_starts_list.
        """
        print("\n" + "="*70)
        print("HARD WALL DEBUG REPORT")
        print("="*70)

        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        found_any = False

        def get_key_term(key):
            parts = key.split("__TERM_")
            return parts[1] if len(parts) == 2 else "FULL"

        def unit_slots(unit_type, unit_key, groups, stackable_cats):
            """All allowed start slots for a unit (union across all sessions in it)."""
            slots = set()
            if unit_type == "hw":
                for s_data in groups[unit_key]:
                    slots.update(s_data["allowed_starts_list"])
            else:
                for hw_key in stackable_cats.get(unit_key, []):
                    for s_data in groups[hw_key]:
                        slots.update(s_data["allowed_starts_list"])
            return slots

        def unit_label(unit_type, unit_key):
            if unit_type == "sc":
                return f"[GROUPED/CONSTRAINED] {unit_key}"
            # Strip __TERM_ suffix for readability
            return unit_key.split("__TERM_")[0]

        for c_id, groups in cohort_to_conflict_groups.items():
            # Calculate how many sessions this cohort must take
            total_required_sessions = sum(len(sessions) for sessions in groups.values())
            
            # Calculate how many slots are actually available
            # (Total slots * days, considering allowed_slots from Categories)
            available_slots = 20
            
            if total_required_sessions > available_slots:
                print(f"CRITICAL ERROR: Cohort {c_id} requires {total_required_sessions} sessions, but only {available_slots} slots exist.")
        for cohort_id, groups in cohort_to_conflict_groups.items():

            # Classify keys into stackable vs hard wall
            stackable_keys = set()
            for key, sessions in groups.items():
                base_key = key.split("__TERM_")[0]
                if base_key.startswith("CONSTRAINED_") or base_key.startswith("GROUPED_"):
                    cat = self.scenario.get_course_category_by_id(
                        sessions[0]["section"].category_id)
                    if cat and cat.choice_type.upper() in ("CONSTRAINED", "GROUPED"):
                        stackable_keys.add(key)

            hard_wall_keys = [k for k in groups.keys() if k not in stackable_keys]

            stackable_cats = {}
            for key in stackable_keys:
                cat = self.scenario.get_course_category_by_id(
                    groups[key][0]["section"].category_id)
                term_id = groups[key][0]["term_id"]
                sc_key = f"{cat.id}__TERM_{term_id}"
                stackable_cats.setdefault(sc_key, []).append(key)

            all_units = []
            for k in hard_wall_keys:
                all_units.append(("hw", k, get_key_term(k)))
            for sc_key in stackable_cats:
                term_id = sc_key.split("__TERM_")[1] if "__TERM_" in sc_key else "FULL"
                all_units.append(("sc", sc_key, term_id))

            if not all_units:
                continue

            # For each distinct term, find the set of units that are mutually
            # competing (all overlap with each other in calendar time).
            # Then check if they can all be assigned distinct slots.
            all_term_ids = list(set(u[2] for u in all_units))

            for term_id in all_term_ids:
                # Units active during this term
                active = [(ut, uk, ut_term) for ut, uk, ut_term in all_units
                        if self._terms_overlap(ut_term, term_id)]
                n = len(active)
                if n <= 1:
                    continue

                # For each unit, compute its available slots (faculty-aware)
                unit_slot_sets = []
                for ut, uk, ut_term in active:
                    slots = unit_slots(ut, uk, groups, stackable_cats)
                    unit_slot_sets.append((ut, uk, ut_term, slots))

                # CHECK 1: Any unit with zero slots — immediately infeasible
                zero_slot_units = [(ut, uk) for ut, uk, _, slots in unit_slot_sets
                                if len(slots) == 0]
                if zero_slot_units:
                    found_any = True
                    print(f"\n❌ ZERO SLOTS — cohort={cohort_id} term={term_id}")
                    for ut, uk in zero_slot_units:
                        print(f"   Unit '{unit_label(ut, uk)}' has NO valid slots at all")
                        # Show sessions and their faculty
                        key_list = [uk] if ut == "hw" else stackable_cats.get(uk, [])
                        for key in key_list:
                            for s_data in groups.get(key, []):
                                sec = s_data["section"]
                                print(f"     Session: {s_data['suffix_key']}")
                                print(f"     Faculty: {sec.faculty_ids}")
                                print(f"     Allowed starts: {s_data['allowed_starts_list']}")

                # CHECK 2: Pairwise slot conflicts — two units share NO common
                # available slot AND no other slot is available for one of them
                # More useful: find the set of ALL slots used by active units
                # and check if there are enough distinct slots for n units.
                # Use a greedy slot-coverage check.
                all_available = set()
                for _, _, _, slots in unit_slot_sets:
                    all_available.update(slots)

                if n > len(all_available):
                    found_any = True
                    print(f"\n❌ NOT ENOUGH SLOTS — cohort={cohort_id} term={term_id}")
                    print(f"   {n} competing units but only {len(all_available)} "
                        f"distinct slots available across all of them")
                    for ut, uk, ut_term, slots in unit_slot_sets:
                        slot_days = sorted(set(
                            days[s // self.slots_per_day] for s in slots))
                        print(f"   [{ut_term}] {unit_label(ut, uk)}: "
                            f"{len(slots)} slots on days {slot_days}")

                # CHECK 3: Faculty conflicts between units — if two NONE units
                # share the same faculty member, they can never be in the same
                # slot, which is fine (Hard Wall already prevents that). But if
                # the shared-faculty constraint ALSO eliminates the only slots
                # available to each, we surface it.
                if len(unit_slot_sets) >= 2:
                    for i in range(len(unit_slot_sets)):
                        ut_i, uk_i, _, slots_i = unit_slot_sets[i]
                        if ut_i != "hw":
                            continue
                        fids_i = set()
                        for s_data in groups.get(uk_i, []):
                            fids_i.update(s_data["section"].faculty_ids)

                        for j in range(i+1, len(unit_slot_sets)):
                            ut_j, uk_j, _, slots_j = unit_slot_sets[j]
                            if ut_j != "hw":
                                continue
                            fids_j = set()
                            for s_data in groups.get(uk_j, []):
                                fids_j.update(s_data["section"].faculty_ids)

                            shared_fac = fids_i & fids_j
                            if not shared_fac:
                                continue

                            # These two units share faculty — their slots must differ
                            # Check if there are enough non-overlapping slots between them
                            # (slots_i - slots_j) must be non-empty AND
                            # (slots_j - slots_i) must be non-empty
                            only_i = slots_i - slots_j
                            only_j = slots_j - slots_i
                            if not only_i or not only_j:
                                found_any = True
                                print(f"\n❌ FACULTY CONFLICT — cohort={cohort_id}")
                                print(f"   Units '{unit_label(ut_i, uk_i)}' and "
                                    f"'{unit_label(ut_j, uk_j)}' share faculty: "
                                    f"{shared_fac}")
                                print(f"   Unit i slots: {sorted(slots_i)}")
                                print(f"   Unit j slots: {sorted(slots_j)}")
                                print(f"   Slots unique to i: {sorted(only_i)}")
                                print(f"   Slots unique to j: {sorted(only_j)}")
                                if not only_i:
                                    print(f"   ⚠️  Unit i has NO slot that unit j "
                                        f"cannot also use — cannot separate them")
                                if not only_j:
                                    print(f"   ⚠️  Unit j has NO slot that unit i "
                                        f"cannot also use — cannot separate them")

                # CHECK 4: Sessions within a single NONE unit that have
                # zero allowed starts — catches individual session problems
                for ut, uk, ut_term, slots in unit_slot_sets:
                    if ut != "hw":
                        continue
                    for s_data in groups.get(uk, []):
                        if len(s_data["allowed_starts_list"]) == 0:
                            found_any = True
                            sec = s_data["section"]
                            print(f"\n❌ ZERO STARTS — cohort={cohort_id}")
                            print(f"   Session: {s_data['suffix_key']}")
                            print(f"   Faculty: {sec.faculty_ids}")
                            print(f"   Category: {sec.category_id}")
                            print(f"   This session has no valid start slots after "
                                f"applying faculty availability and allowed slots")

        if not found_any:
            print("No Hard Wall issues detected.")
            print("If infeasibility persists, it is likely caused by:")
            print("  - Room capacity/type constraints (too few rooms for sessions)")
            print("  - Faculty NoOverlap (faculty has more sessions than available slots)")
            print("  - GROUPED common slots becoming empty after other constraints apply")

        print("="*70 + "\n")

    def add_unified_cohort_constraints(self):
        print("--- Applying Cohort Constraints ---")

        #print(f"At start of add_unified_cohort_constraints: {len(self.model.Proto().constraints)} constraints")
        cohort_to_conflict_groups = self._build_conflict_groups()

        self._build_start_literals()
        #print(f"After _build_start_literals: {len(self.model.Proto().constraints)} constraints")

        self._add_section_alignment()
        #print(f"After _add_section_alignment: {len(self.model.Proto().constraints)} constraints")

        local_flags_by_cohort = self._add_stacking_constraints(cohort_to_conflict_groups)
        #print(f"After _add_stacking_constraints: {len(self.model.Proto().constraints)} constraints")
        self._debug_hard_wall(cohort_to_conflict_groups)
        self._add_hard_wall(cohort_to_conflict_groups, local_flags_by_cohort)
        #sys.exit(0)
        #print(f"After _add_hard_wall: {len(self.model.Proto().constraints)} constraints")

    def _build_conflict_groups(self):
        """
        Step 1: Build { cohort_id: { conflict_key: [sessions] } }.
        Consistent conflict key naming for all types:
          NONE category        -> NONE_{course_id}_{s_type}_{session_index}
          CONSTRAINED count=1  -> CONSTRAINED_{cat_id}_{s_type}_{session_index}
          CONSTRAINED count>1  -> CONSTRAINED_{cat_id}_{s_type}_{session_index}
        Distinction between count=1 and count>1 is handled in stacking logic, not in key name.

        The purpose of this function is to group of sessions for each cohort which should
        not be scheduled together. Each conflict key represents a set of session which
        should NOT be scheduled together with sessions of other conflict_keys for that
        cohort.
        """
        cohort_to_conflict_groups = {}

        for suffix, data in self.session_vars.items():
            data["suffix_key"] = suffix
            section = data["section"]
            cat = self.scenario.get_course_category_by_id(section.category_id)
            if not cat:
                continue

            session_type = data["type"]
            session_index = suffix.split("_")[-1]
            choice_type = cat.choice_type.upper()

            if choice_type == "CONSTRAINED":
                if cat.choice_count > 1:
                    # All sessions 0s of such cats should be together and all session 1s shd be together
                    # and the conflict_key is used in the stacking logic later so need this format.
                    conflict_key = f"CONSTRAINED_{cat.id}_{session_type}_{session_index}"
                else:
                    conflict_key = f"CONSTRAINED_{cat.id}"                
            elif choice_type == "NONE":
                conflict_key = f"NONE_{section.course_id}"
            elif choice_type == "GROUPED":
                conflict_key = f"GROUPED_{cat.id}"
            elif choice_type in ('VIRTUAL_STAFFED', 'VIRTUAL_OPEN'):
                conflict_key = f"NONE_{section.course_id}"                
            else:
                continue

            for cohort_raw in section.eligible_cohorts:
                cohort_id = cohort_raw.strip().upper()
                if cohort_id not in cohort_to_conflict_groups:
                    cohort_to_conflict_groups[cohort_id] = {}
                term_scoped_key = f"{conflict_key}__TERM_{section.term_id}"
                if term_scoped_key not in cohort_to_conflict_groups[cohort_id]:
                    cohort_to_conflict_groups[cohort_id][term_scoped_key] = []
                cohort_to_conflict_groups[cohort_id][term_scoped_key].append(data)

        # total_stacking_keys = set()
        # for cohort_id, groups in cohort_to_conflict_groups.items():
        #     for key, sessions in groups.items():
        #         if key.startswith("CONSTRAINED_"):
        #             sample_cat = self.scenario.get_course_category_by_id(
        #                 sessions[0]["section"].category_id)
        #             if sample_cat and sample_cat.choice_count > 1:
        #                 total_stacking_keys.add(key)
        # print(f"\nTotal CONSTRAINED stacking keys across all cohorts: {len(total_stacking_keys)}")
        # print(f"Keys: {total_stacking_keys}")
        #print(cohort_to_conflict_groups["BSBIO25"].keys())
        #sys.exit(0)
        return cohort_to_conflict_groups

    def _build_start_literals(self):
        """
        Step 2: For every session, create one BoolVar per allowed start slot.
        Exactly one literal is true (the chosen start). Stores in self.session_start_lits.
        For every session that needs to be scheduled, this function creates a set 
        of yes/no flags — one flag for each time slot where that session is allowed to start.
        For example, if a theory session can legally start at slots 1, 2, 7, or 8, then four 
        flags are created: "starts at slot 1", "starts at slot 2", "starts at slot 7", "starts at slot 8".

        Two rules are then enforced:
        Rule 1 — If a flag is true (the session starts at that slot), then the session's start time is 
        locked to that slot. The flag and the start time are kept in sync — 
        you can't say "starts at slot 7" is true but have the session actually start at slot 2.

        Rule 2 — Exactly one flag must be true. The session must start somewhere, and it can only start 
        at one time. Not zero, not two — exactly one.

        The reason for creating these flags rather than just working with the start time directly 
        is that many of the later constraints — the Hard Wall, the stacking logic, the meeting slot 
        penalties — need to reason about individual slots. For example, "if this session starts at 
        slot 7 and runs for 2 slots, then slots 7 and 8 are occupied." It's much easier to express 
        this kind of slot-level reasoning using yes/no flags than using arithmetic on the start time variable.

        Think of it like a booking system — instead of just recording "this session starts at time X", 
        you're pre-creating a checkbox for every possible time, and the solver must tick exactly one of them.
        """        

        for suffix, data in self.session_vars.items():
            #before = len(self.model.Proto().constraints)
            lits = {t: self.model.NewBoolVar(f'lit_{suffix}_{t}') for t in data["allowed_starts_list"]}
            for t, lit in lits.items():
                self.model.Add(data["start"] == t).OnlyEnforceIf(lit)
            self.model.Add(sum(lits.values()) == 1)
            self.session_start_lits[suffix] = lits
            #after = len(self.model.Proto().constraints)
            # if before <= 20219 < after:
            #     print(f"Constraint #20219 created by session: {suffix}, allowed_starts: {data['allowed_starts_list']}")
            

    def _add_section_alignment(self):
        """
        Step 3: Soft alignment — penalize pairs of sections of the same course,
        same category, same session type and index, that start at different slots.
        Skips pairs sharing the same faculty (they cannot share a slot anyway).
        Skips CONSTRAINED count>1 — stacking constraints handle those.
        """
        course_session_groups = {}
        for suffix, data in self.session_vars.items():
            section = data["section"]
            cat = self.scenario.get_course_category_by_id(section.category_id)
            if not cat or cat.choice_type.upper() not in ["NONE", "CONSTRAINED", "COMPLETE", "GROUPED"]:
                continue
            if cat.choice_type.upper() == "CONSTRAINED" and cat.choice_count > 1:
                continue
            session_type = data["type"]
            session_index = suffix.split("_")[-1]
            group_key = f"{section.course_id}_{section.category_id}_{session_type}_{session_index}"
            if group_key not in course_session_groups:
                course_session_groups[group_key] = []
            course_session_groups[group_key].append(suffix)

        for group_key, suffixes in course_session_groups.items():
            if len(suffixes) < 2:
                continue
            for i in range(len(suffixes)):
                for j in range(i + 1, len(suffixes)):
                    fids_i = set(self.session_vars[suffixes[i]]["section"].faculty_ids)
                    fids_j = set(self.session_vars[suffixes[j]]["section"].faculty_ids)
                    if fids_i & fids_j:  
                        # any shared faculty
                        # Warn but dont group together and continue
                        print(f"⚠️ {self.session_vars[suffixes[i]]["section"].id} and {self.session_vars[suffixes[j]]["section"].id} share common faculty so cannot group them together!")
                        continue
                    term_i = self.session_vars[suffixes[i]]["term_id"]
                    term_j = self.session_vars[suffixes[j]]["term_id"]
                    if not self._terms_overlap(term_i, term_j):
                        continue                    
                    start_i = self.session_vars[suffixes[i]]["start"]
                    start_j = self.session_vars[suffixes[j]]["start"]
                    not_aligned = self.model.NewBoolVar(f'not_aligned_{group_key}_{i}_{j}')
                    self.model.Add(start_i == start_j).OnlyEnforceIf(not_aligned.Not())
                    #self.model.Add(start_i != start_j).OnlyEnforceIf(not_aligned)
                    self.penalties.append(not_aligned * 200)
                    self.conflicts.append({
                        "type": "SECTION_ALIGNMENT",
                        "var": not_aligned,
                        "sections": [f"{group_key}_pair_{i}_{j}"]
                    })

    def _add_stacking_constraints(self, cohort_to_conflict_groups):
        """
        Step 4: For each cohort, build local_flags (one BoolVar per key per slot)
        and apply vertical stacking for CONSTRAINED count>1 categories —
        grouping courses into choice_count-sized groups each sharing a slot.
        Returns local_flags_by_cohort { cohort_id: local_flags } for use by _add_hard_wall.
        """
        local_flags_by_cohort = {}

        for cohort_id, groups in cohort_to_conflict_groups.items():
            local_flags = {}
            course_flags_by_key = {}  # { key: { course_id: [BoolVar per slot] } }

            # Build local_flags and course_flags for every key in this cohort
            for key, sessions in groups.items():
                flags = [self.model.NewBoolVar(f'act_{cohort_id}_{key}_t{t}') for t in range(self.total_slots)]
                local_flags[key] = flags

                sample_cat = self.scenario.get_course_category_by_id(
                    sessions[0]["section"].category_id)
                if key.split("__TERM_")[0].startswith("CONSTRAINED_") and sample_cat and sample_cat.choice_count > 1:
                    # CONSTRAINED count>1: build per-course flags for stacking
                    course_flags = {}
                    for s_data in sessions:
                        course_id = s_data["section"].course_id
                        if course_id not in course_flags:
                            course_flags[course_id] = [
                                self.model.NewBoolVar(f'cf_{cohort_id}_{key}_{course_id}_t{t}')
                                for t in range(self.total_slots)
                            ]
                        lits = self.session_start_lits[s_data["suffix_key"]]
                        for st, lit in lits.items():
                            for offset in range(s_data["duration"]):
                                t_occ = st + offset
                                if t_occ < self.total_slots:
                                    self.model.Add(course_flags[course_id][t_occ] == 1).OnlyEnforceIf(lit)
                                    self.model.Add(flags[t_occ] == 1).OnlyEnforceIf(lit)
                    course_flags_by_key[key] = course_flags
                else:
                    # All other keys: just bucket-level flags
                    for s_data in sessions:
                        lits = self.session_start_lits[s_data["suffix_key"]]
                        for st, lit in lits.items():
                            for offset in range(s_data["duration"]):
                                t_occ = st + offset
                                if t_occ < self.total_slots:
                                    self.model.Add(flags[t_occ] == 1).OnlyEnforceIf(lit)

            # Vertical stacking for CONSTRAINED count>1
            relevant_cats = {}
            for key, sessions in groups.items():
                if key.split("__TERM_")[0].startswith("CONSTRAINED_"):
                    sample_session = sessions[0]
                    cat = self.scenario.get_course_category_by_id(sample_session["section"].category_id)
                    if cat and cat.choice_type.upper() == "CONSTRAINED" and cat.choice_count > 1:
                        if cat.id not in relevant_cats:
                            relevant_cats[cat.id] = []
                        relevant_cats[cat.id].append(key)

            for cat_id, keys_in_cat in relevant_cats.items():
                cat = self.scenario.get_course_category_by_id(cat_id)

                all_allowed_starts = set()
                for key in keys_in_cat:
                    for s_data in groups[key]:
                        for st in self.session_start_lits[s_data["suffix_key"]].keys():
                            all_allowed_starts.add(st)
                all_allowed_starts = sorted(list(all_allowed_starts))

                course_ids = list(course_flags_by_key[keys_in_cat[0]].keys())
                n_courses = len(course_ids)
                n_groups = -(-n_courses // cat.choice_count)  # ceil division

                # One group assignment per course, shared across all session indexes
                course_group = {}
                for cid in course_ids:
                    course_group[cid] = self.model.NewIntVar(
                        0, n_groups - 1, f'group_{cohort_id}_{cat_id}_{cid}'
                    )

                # One slot variable per group per session key
                group_slot = {}
                for key in keys_in_cat:
                    group_slot[key] = {}
                    for g in range(n_groups):
                        group_slot[key][g] = self.model.NewIntVarFromDomain(
                            cp_model.Domain.FromValues(all_allowed_starts),
                            f'gslot_{cohort_id}_{cat_id}_{key}_g{g}'
                        )
                    if len(group_slot[key]) > 1:
                        self.model.AddAllDifferent(list(group_slot[key].values()))

                # Link each session's start to its group's slot
                for key in keys_in_cat:
                    for s_data in groups[key]:
                        cid = s_data["section"].course_id
                        start_var = s_data["start"]
                        for g in range(n_groups):
                            is_in_group = self.model.NewBoolVar(
                                f'ingroup_{cohort_id}_{cat_id}_{cid}_{key}_g{g}'
                            )
                            self.model.Add(course_group[cid] == g).OnlyEnforceIf(is_in_group)
                            self.model.Add(course_group[cid] != g).OnlyEnforceIf(is_in_group.Not())
                            self.model.Add(start_var == group_slot[key][g]).OnlyEnforceIf(is_in_group)

                # Group sizes <= choice_count
                for g in range(n_groups):
                    members = []
                    for cid in course_ids:
                        m = self.model.NewBoolVar(f'member_{cohort_id}_{cat_id}_{cid}_g{g}')
                        self.model.Add(course_group[cid] == g).OnlyEnforceIf(m)
                        self.model.Add(course_group[cid] != g).OnlyEnforceIf(m.Not())
                        members.append(m)
                    self.model.Add(sum(members) <= cat.choice_count)

            # Forced co-scheduling for GROUPED categories
            # Only co-schedule sessions of the same type and index together
            for key, sessions in groups.items():
                if not key.split("__TERM_")[0].startswith("GROUPED_"):
                    continue
                if len(sessions) < 2:
                    continue
                session_type_groups = {}
                for s in sessions:
                    s_type = s["type"]
                    s_idx = s["suffix_key"].split("_")[-1]
                    tkey = (s_type, s_idx)
                    if tkey not in session_type_groups:
                        session_type_groups[tkey] = []
                    session_type_groups[tkey].append(s)

                for (s_type, s_idx), type_sessions in session_type_groups.items():
                    if len(type_sessions) < 2:
                        continue
                    all_lits = [self.session_start_lits[s["suffix_key"]] for s in type_sessions]
                    common_slots = set(all_lits[0].keys())
                    for lits in all_lits[1:]:
                        common_slots &= set(lits.keys())
                    if not common_slots:
                        print(f"❌ NO COMMON SLOTS for GROUPED key {key} {s_type}_{s_idx}")
                        continue
                    for i in range(len(type_sessions)):
                        for j in range(i + 1, len(type_sessions)):
                            lits_i = all_lits[i]
                            lits_j = all_lits[j]
                            for t in common_slots:
                                self.model.AddBoolOr([lits_i[t].Not(), lits_j[t]])
                                self.model.AddBoolOr([lits_j[t].Not(), lits_i[t]])

            local_flags_by_cohort[cohort_id] = local_flags

        return local_flags_by_cohort

    def _add_hard_wall(self, cohort_to_conflict_groups, local_flags_by_cohort):
        """
        Step 5: For each cohort, enforce that at most one conflict_key is active
        at any slot. CONSTRAINED count>1 keys are collapsed to a single cat_active
        flag per category so their internal stacking doesn't count as multiple active keys.
        """
        # Create a list to store our debug variables if it doesn't exist
        if not hasattr(self, 'hard_wall_violations'):
            self.hard_wall_violations = []

        for cohort_id, groups in cohort_to_conflict_groups.items():
            local_flags = local_flags_by_cohort[cohort_id]

            # Identify stackable keys (CONSTRAINED count>1 and GROUPED)
            stackable_keys = set()
            for key, sessions in groups.items():
                base_key = key.split("__TERM_")[0]
                # if cohort_id == 'BSBIO25':
                #     print("=== ", key, base_key)                
                if base_key.startswith("CONSTRAINED_") or base_key.startswith("GROUPED_"):
                    cat = self.scenario.get_course_category_by_id(
                        sessions[0]["section"].category_id)
                    if cat and cat.choice_type.upper() in ("CONSTRAINED", "GROUPED"):
                        # if cohort_id == 'BSBIO25':
                        #     print("Adding ", key)                        
                        stackable_keys.add(key)
            #print(cohort_id, stackable_keys)
            hard_wall_keys = [k for k in groups.keys() if k not in stackable_keys]
            if cohort_id == 'BSBIO25':
                print("--- ", stackable_keys, hard_wall_keys)

            # Group stackable keys by category+term
            stackable_cats = {}
            for key in stackable_keys:
                sample_session = groups[key][0]
                cat = self.scenario.get_course_category_by_id(sample_session["section"].category_id)
                term_id = groups[key][0]["term_id"]
                stackable_cat_key = f"{cat.id}__TERM_{term_id}"
                if stackable_cat_key not in stackable_cats:
                    stackable_cats[stackable_cat_key] = []
                # if cohort_id == 'BSBIO25':
                #     print("AAAAA--- ", key, stackable_cat_key, cat, sample_session)
                stackable_cats[stackable_cat_key].append(key)

            # Get term_id for each key
            def get_key_term(key):
                parts = key.split("__TERM_")
                return parts[1] if len(parts) == 2 else "FULL"

            # Build all units (hard_wall + stackable_cats) with their term_ids
            all_units = []  # list of (flag_or_key, term_id, is_stackable_cat)
            for k in hard_wall_keys:
                # if cohort_id == 'BSBIO25':
                #     print("Appending hw ", get_key_term(k))
                all_units.append(("hw", k, get_key_term(k)))
            for sc_key in stackable_cats:
                term_id = sc_key.split("__TERM_")[1] if "__TERM_" in sc_key else "FULL"
                # if cohort_id == 'BSBIO25':
                #     print(f"!! {sc_key}, {term_id}, {get_key_term(sc_key)}")
                #     print(term_id)
                all_units.append(("sc", sc_key, get_key_term(sc_key)))

            for t in range(self.total_slots):
                # Build list of (flag, term_id) for this slot
                unit_flags = []
                for unit_type, unit_key, term_id in all_units:
                    if unit_type == "hw":
                        unit_flags.append((local_flags[unit_key][t], term_id, unit_key))
                    else:  # stackable cat
                        keys_in_cat = stackable_cats[unit_key]
                        cat_active = self.model.NewBoolVar(f'cat_active_{cohort_id}_{unit_key}_t{t}')
                        self.model.AddMaxEquality(cat_active, [local_flags[k][t] for k in keys_in_cat])
                        # if cohort_id == 'BSBIO25':
                        #     print(f"!!!!!! {unit_key}")                        
                        unit_flags.append((cat_active, term_id, unit_key))

                # Apply pairwise SOFT CONSTRAINT
                for i in range(len(unit_flags)):
                    flag_i, term_i, name_i = unit_flags[i]
                    for j in range(i + 1, len(unit_flags)):
                        flag_j, term_j, name_j = unit_flags[j]
                        # if cohort_id == 'BSBIO25':
                        #     print(name_i, name_j)
                        
                        if self._terms_overlap(term_i, term_j):
                            # --- THE SOFT WALL LOGIC ---
                            # Create a boolean variable that flips to 1 ONLY IF the wall is broken
                            violation = self.model.NewBoolVar(f'hw_viol_c{cohort_id}_t{t}_{name_i}_vs_{name_j}')
                            
                            # Allow flag_i + flag_j to equal 2 ONLY IF violation == 1
                            self.model.Add(flag_i + flag_j <= 1 + violation)
                            
                            # Make the solver hate using the violation variable
                            self.penalties.append(violation * 1000000)
                            
                            # Save it for the post-solve report
                            self.hard_wall_violations.append({
                                'var': violation,
                                'cohort': cohort_id,
                                'slot': t,
                                'unit_1': name_i,
                                'unit_2': name_j
                            })
        #sys.exit(0)
    # def _add_hard_wall(self, cohort_to_conflict_groups, local_flags_by_cohort):
    #     """
    #     Step 5: For each cohort, enforce that at most one conflict_key is active
    #     at any slot. CONSTRAINED count>1 keys are collapsed to a single cat_active
    #     flag per category so their internal stacking doesn't count as multiple active keys.
    #     """
    #     for cohort_id, groups in cohort_to_conflict_groups.items():
    #         local_flags = local_flags_by_cohort[cohort_id]

    #         # Identify stackable keys (CONSTRAINED count>1 and GROUPED)
    #         stackable_keys = set()
    #         for key, sessions in groups.items():
    #             base_key = key.split("__TERM_")[0]
    #             if base_key.startswith("CONSTRAINED_") or base_key.startswith("GROUPED_"):
    #                 cat = self.scenario.get_course_category_by_id(
    #                     sessions[0]["section"].category_id)
    #                 if cat and cat.choice_type.upper() in ("CONSTRAINED", "GROUPED"):
    #                     stackable_keys.add(key)
    #         print(cohort_id, stackable_keys)
    #         hard_wall_keys = [k for k in groups.keys() if k not in stackable_keys]

    #         # Group stackable keys by category+term
    #         stackable_cats = {}
    #         for key in stackable_keys:
    #             sample_session = groups[key][0]
    #             cat = self.scenario.get_course_category_by_id(sample_session["section"].category_id)
    #             term_id = groups[key][0]["term_id"]
    #             stackable_cat_key = f"{cat.id}__TERM_{term_id}"
    #             if stackable_cat_key not in stackable_cats:
    #                 stackable_cats[stackable_cat_key] = []
    #             stackable_cats[stackable_cat_key].append(key)

    #         # Get term_id for each key
    #         def get_key_term(key):
    #             parts = key.split("__TERM_")
    #             return parts[1] if len(parts) == 2 else "FULL"

    #         # Build all units (hard_wall + stackable_cats) with their term_ids
    #         all_units = []  # list of (flag_or_key, term_id, is_stackable_cat)
    #         for k in hard_wall_keys:
    #             all_units.append(("hw", k, get_key_term(k)))
    #         for sc_key in stackable_cats:
    #             term_id = sc_key.split("__TERM_")[1] if "__TERM_" in sc_key else "FULL"
    #             all_units.append(("sc", sc_key, term_id))

    #         for t in range(self.total_slots):
    #             # For each pair of units, only add Hard Wall between overlapping terms
    #             # Build the usage flags for units that overlap with each other
    #             # Group units into temporal overlap clusters
    #             # Within each cluster, sum <= 1
                
    #             # Build list of (flag, term_id) for this slot
    #             unit_flags = []
    #             for unit_type, unit_key, term_id in all_units:
    #                 if unit_type == "hw":
    #                     unit_flags.append((local_flags[unit_key][t], term_id))
    #                 else:  # stackable cat
    #                     keys_in_cat = stackable_cats[unit_key]
    #                     cat_active = self.model.NewBoolVar(f'cat_active_{cohort_id}_{unit_key}_t{t}')
    #                     self.model.AddMaxEquality(cat_active, [local_flags[k][t] for k in keys_in_cat])
    #                     unit_flags.append((cat_active, term_id))

    #             # Apply pairwise: if two units overlap in time, they can't both be active
    #             for i in range(len(unit_flags)):
    #                 flag_i, term_i = unit_flags[i]
    #                 for j in range(i + 1, len(unit_flags)):
    #                     flag_j, term_j = unit_flags[j]
    #                     if self._terms_overlap(term_i, term_j):
    #                         self.model.Add(flag_i + flag_j <= 1)

    def add_preferred_building_constraints(self, penalty=1000):
        for suffix, data in self.session_vars.items():
            section = data["section"]
            preferred_theory_buildings = section.preferred_theory_buildings
            preferred_lab_buildings = section.preferred_lab_buildings
            if not preferred_theory_buildings and not preferred_lab_buildings:
                continue
            for room_id, presence_var in data["presence_map"].items():
                room = self.scenario.get_location_by_id(room_id)
                if room.type in ["CLASSROOM", "EITHER"] and  preferred_theory_buildings and room.building not in preferred_theory_buildings:
                    self.penalties.append(presence_var * penalty)
                    self.conflicts.append({
                        "type": "PREFERRED_THEORY_BUILDING",
                        "var": presence_var,
                        "section_id": suffix,
                        "requested_buildings": section.preferred_theory_buildings,
                        "alloted_building": room.building
                    })
                if room.type in ["LAB", "EITHER"] and  preferred_lab_buildings and room.building not in preferred_lab_buildings:
                    self.penalties.append(presence_var * penalty)
                    self.conflicts.append({
                        "type": "PREFERRED_LAB_BUILDING",
                        "var": presence_var,
                        "section_id": suffix,
                        "requested_buildings": section.preferred_lab_buildings,
                        "alloted_building": room.building
                    })                    

    def add_preferred_room_layout_constraints(self, penalty=2000):
        for suffix, data in self.session_vars.items():
            section = data["section"]
            preferred_theory_layouts = set(section.preferred_theory_layouts) if section.preferred_theory_layouts else None
            preferred_lab_layouts = set(section.preferred_lab_layouts) if section.preferred_lab_layouts else None
            if not preferred_theory_layouts and not preferred_lab_layouts:
                continue
            for room_id, presence_var in data["presence_map"].items():
                room = self.scenario.get_location_by_id(room_id)
                layouts = room.layouts
                layouts_set = None
                if layouts:
                    layouts_set = set(layouts)
                if layouts_set and room.type in ["CLASSROOM", "EITHER"] and preferred_theory_layouts and not layouts_set.intersection(preferred_theory_layouts):
                    self.penalties.append(presence_var * penalty)
                    self.conflicts.append({
                        "type": "PREFERRED_THEORY_LAYOUTS",
                        "var": presence_var,
                        "section_id": suffix,
                        "requested_layouts": section.preferred_theory_layouts,
                        "alloted_layouts": room.layouts
                    })
                if layouts_set and room.type in ["LAB", "EITHER"] and preferred_lab_layouts and not layouts_set.intersection(preferred_lab_layouts):
                    self.penalties.append(presence_var * penalty)
                    self.conflicts.append({
                        "type": "PREFERRED_LAB_LAYOUTS",
                        "var": presence_var,
                        "section_id": suffix,
                        "requested_layouts": section.preferred_lab_layouts,
                        "alloted_layouts": room.layouts
                    })                    

    def add_cohort_spreading_soft_constraints(self, empty_day_penalty=4000, overcrowding_penalty=40, max_ideal_classes=2):
        """
        Soft constraint: Spreads a cohort's workload evenly across the week.
        Penalizes days with 0 classes heavily, and penalizes days with high density mildly.
        """
        print("--- Applying Soft Constraint: Cohort Workload Spreading ---")

        slots_per_day = self.scenario.config.slots_per_day
        # Fallback to 5 days if days_per_week isn't explicitly configured
        num_days = getattr(self.scenario.config, 'days_per_week', 5) 

        # 1. Map every session's day presence to boolean flags
        # session_day_bools[suffix][day_index] -> BoolVar (1 if session is on that day)
        session_day_bools = defaultdict(dict)

        for suffix, data in self.session_vars.items():
            start_var = data["start"]
            
            # Channel linear slot index to a specific day index (day = start // slots_per_day)
            day_var = self.model.NewIntVar(0, num_days - 1, f"day_{suffix}")
            self.model.AddDivisionEquality(day_var, start_var, slots_per_day)
            
            # Create clear boolean indicators for each day
            for d in range(num_days):
                b = self.model.NewBoolVar(f"session_{suffix}_on_day_{d}")
                self.model.Add(day_var == d).OnlyEnforceIf(b)
                self.model.Add(day_var != d).OnlyEnforceIf(b.Not())
                session_day_bools[suffix][d] = b

        # 2. Group sessions by Cohort ID
        cohort_to_sessions = defaultdict(list)
        for suffix, data in self.session_vars.items():
            section = data["section"]
            raw_cohorts = getattr(section, 'cohorts', [])
            for cohort in raw_cohorts:
                # Handle object vs raw string safely
                cohort_id = cohort.id if hasattr(cohort, 'id') else str(cohort)
                cohort_to_sessions[cohort_id].append(suffix)

        # 3. Apply the Push-Pull Penalties per Cohort per Day
        zero_const = self.model.NewConstant(0)

        for cohort_id, session_suffixes in cohort_to_sessions.items():
            for d in range(num_days):
                # Gather all session day-booleans matching this cohort for day 'd'
                cohort_day_vars = [session_day_bools[suffix][d] for suffix in session_suffixes]
                
                if not cohort_day_vars:
                    continue
                
                # Count how many classes this cohort has today
                num_classes_today = self.model.NewIntVar(0, len(cohort_day_vars), f"count_{cohort_id}_day_{d}")
                self.model.Add(num_classes_today == sum(cohort_day_vars))

                # --- PART A: THE PULL (Avoid 0-class days) ---
                day_is_active = self.model.NewBoolVar(f"cohort_{cohort_id}_active_day_{d}")
                self.model.Add(num_classes_today >= 1).OnlyEnforceIf(day_is_active)
                self.model.Add(num_classes_today == 0).OnlyEnforceIf(day_is_active.Not())
                
                # Penalize if day_is_active is False (which means day_is_active.Not() is True)
                self.penalties.append(day_is_active.Not() * empty_day_penalty)

                # # --- PART B: THE PUSH (Spread out high density days) ---
                # # Compute: diff = num_classes_today - max_ideal_classes
                # diff_var = self.model.NewIntVar(-max_ideal_classes, len(cohort_day_vars), f"diff_{cohort_id}_day_{d}")
                # self.model.Add(diff_var == num_classes_today - max_ideal_classes)
                
                # # Compute: excess = max(0, diff)
                # excess = self.model.NewIntVar(0, len(cohort_day_vars), f"excess_{cohort_id}_day_{d}")
                # self.model.AddMaxEquality(excess, [zero_const, diff_var])
                
                # # Penalize linearly for every class over the ideal threshold
                # self.penalties.append(excess * overcrowding_penalty)

    def add_constraints(self):

        # Add the constraint that only one one room should be picked for a session - assignment constraint
        for suffix, data in self.session_vars.items():
            self.model.Add(sum(data["presences"]) == 1)
        #print(f"After room assignment: {len(self.model.Proto().constraints)} constraints")

        # Ensure that no two sessions in the same room can overlap. - collision constraint
        for loc_id, intervals in self.room_intervals.items():
            self.model.AddNoOverlap(intervals)
        #print(f"After room no-overlap: {len(self.model.Proto().constraints)} constraints")

        # Make sure that none of the faculty's session intervals overlap - basically
        # ensuring that they are not double booked
        self.add_faculty_constraints()

        #print(f"After faculty constraints: {len(self.model.Proto().constraints)} constraints")

        self.add_daily_distribution_constraints()
        #print(f"After daily distribution: {len(self.model.Proto().constraints)} constraints")

        self.add_unified_cohort_constraints()
        self.add_meeting_slot_penalties()
        self.add_faculty_rest_soft_constraint()        
        self.add_preferred_building_constraints()
        self.add_cohort_spreading_soft_constraints()
        self.add_preferred_room_layout_constraints()


    def inspect_cohort_buckets(self, target_cohort="BScBio24"):
        print(f"\n{'='*60}")
        print(f"DEBUG INSPECTOR: CONSTRAINED BUCKETS FOR {target_cohort}")
        print(f"{'='*60}")

        # 1. Group by Category ID
        buckets = {} # { cat_id: { course_id: [session_indices] } }

        for suffix, data in self.session_vars.items():
            section = data["section"]
            
            # Only look at our target cohort
            #print(target_cohort, section.eligible_cohorts)
            if target_cohort not in section.eligible_cohorts:
                 continue
                
            cat = self.scenario.get_course_category_by_id(section.category_id)
            print(cat)

            if not cat or cat.choice_type.upper() != "CONSTRAINED":
                continue

            c_id = section.course_id
            cat_id = cat.id
            s_idx = suffix.split("_")[-1]

            if cat_id not in buckets:
                buckets[cat_id] = {}
            if c_id not in buckets[cat_id]:
                buckets[cat_id][c_id] = []
            
            buckets[cat_id][c_id].append(s_idx)

        # 2. Print the findings
        if not buckets:
            print(f"No constrained courses found for cohort {target_cohort}.")
            return

        for cat_id, courses in buckets.items():
            print(f"\n📂 CATEGORY BUCKET: {cat_id}")
            print(f"{'-'*30}")
            for c_id, sessions in courses.items():
                session_str = ", ".join([f"Session {s}" for s in sorted(sessions)])
                print(f"  → Course: {c_id.ljust(15)} | {session_str}")
        
        print(f"\n{'='*60}\n")


    def check_resource_load(self):
        # Check Faculty Load
        for f_id, intervals in self.faculty_intervals.items():
            total_duration = sum(data["duration"] for data in self.session_vars.values() 
                                if f_id in data["section"].faculty_ids)
            avail_hours = len(self.faculty_map[f_id].available_slots)
            if total_duration > avail_hours:
                print(f"Faculty {f_id}: Assigned {total_duration} slots but only has {avail_hours} available.")

        # Check Cohort Load
        for c_id, intervals in self.cohort_intervals.items():
            total_duration = sum(data["duration"] for data in self.session_vars.values() 
                                if c_id in data["section"].eligible_cohorts)
            #print(f"Cohort {c_id}: Assigned {total_duration} slots.")

    def run_preflight_audit(self):
        print("--- 🔍 STARTING PRE-FLIGHT RESOURCE AUDIT ---")
        
        # 1. CHECK FOR "ZERO-OPTION" SESSIONS
        # If any session has 0 allowed starts, the model is dead.
        error_count = 0
        for suffix, data in self.session_vars.items():
            # Check that each section has enough distinct days for its sessions
            section = data["section"]
            course = self.scenario.get_course_by_id(section.course_id)
            total_sessions = len(course.theory_durations) + len(course.lab_durations)
            available_days = set(s // self.slots_per_day for s in data["allowed_starts_list"])
            if len(available_days) < total_sessions:
                print(f"❌ DAY CONFLICT: {suffix} needs {total_sessions} different days "
                    f"but only {len(available_days)} days available: {sorted(available_days)}")  
                error_count += 1          
            # Note: We need to store the 'allowed_starts' count in create_variables
            num_options = len(data["allowed_starts_list"]) 
            if num_options == 0:
                print(f"❌ SESSION ERROR: {suffix} has ZERO valid starting positions. Check Faculty/Category rules.")
                error_count += 1

        for suffix, data in self.session_vars.items():
            if len(data["allowed_starts_list"]) == 0:
                print(f"❌ ZERO STARTS: {suffix}")
            if len(data["allowed_starts_list"]) <= 2:
                print(f"⚠️ LOW OPTIONS: {suffix} only has {len(data['allowed_starts_list'])} allowed starts: {data['allowed_starts_list']}")
        # 2. FACULTY CAPACITY VS. AVAILABILITY
        # Sum of class durations vs. total unique 'allowed' slots
        for f_id, f_intervals in self.faculty_intervals.items():
            # Get all sessions for this faculty
            faculty_sessions = [d for d in self.session_vars.values() if f_id in d["section"].faculty_ids]
            total_needed_slots = sum(d["duration"] for d in faculty_sessions)
            
            # Calculate the "Union" of all valid slots for all their sessions
            # This tells us: "In a perfect world, how many distinct slots could this teacher use?"
            all_possible_slots = set()
            for d in faculty_sessions:
                for start_idx in d["allowed_starts_list"]:
                    for offset in range(d["duration"]):
                        all_possible_slots.add(start_idx + offset)
            
            available_count = len(all_possible_slots)
            if total_needed_slots > available_count:
                print(f"❌ FACULTY CONFLICT [{f_id}]: Needs {total_needed_slots} slots but only has {available_count} valid openings in their schedule.")
                error_count += 1

        # 3. LOCATION CAPACITY (The "Bucket" Check)
        # Sum of all session durations vs. total available room hours
        # This is a common reason for Room NoOverlap failure.
        theory_durations = sum(d["duration"] for d in self.session_vars.values() if "THEORY" in d["type"])
        lab_durations = sum(d["duration"] for d in self.session_vars.values() if "LAB" in d["type"])
        
        # Simple check: (Rooms * Slots) vs Total Class Hours
        # (Refine this by checking specific room types)
        print(f"📊 LOAD CHECK: Theory Hours: {theory_durations}, Lab Hours: {lab_durations}")
        
        print("--- 🔎 AUDIT COMPLETE ---")
        if error_count > 0:
            sys.exit(0)

    def report_meeting_violations(self, solver):
        print("\n=== MEETING SLOT VIOLATION REPORT ===")
        fired = [v for v in self.meeting_violations 
                if solver.BooleanValue(v["var"])]
        
        print(f"Sessions forced into meeting slots: {len(fired)}")
        if fired:
            print("\nViolating sessions:")
            for v in fired:
                section = v["section"]
                course = self.scenario.get_course_by_id(section.course_id)
                faculty_names = [self.faculty_map[fid].id for fid in section.faculty_ids]
                print(f"    Faculty:  {', '.join(faculty_names)}")
                print(f"  {v['suffix']}")
                print(f"    Course:   {course.id} — {course.name}")
                print(f"    Cohorts:  {section.eligible_cohorts}")
                print(f"    Slot:     {v['slot']} "
                    f"(Day {v['slot']//6}, Slot {v['slot']%6})")
                print(f"    All allowed starts: "
                    f"{self.session_vars[v['suffix']]['allowed_starts_list']}")

    def save_solution_hint(self, solver, filepath: str):
        """Save the current solution's start values to a JSON file for use as hints in future runs."""
        import json
        hints = {}
        for suffix, data in self.session_vars.items():
            hints[suffix] = solver.Value(data["start"])
        with open(filepath, 'w') as f:
            json.dump(hints, f, indent=2)
        print(f"Solution hint saved to {filepath} ({len(hints)} sessions)")

    def load_solution_hint(self, filepath: str):
        """Load a previously saved solution and add as hints to the model."""
        import json
        import os
        if not os.path.exists(filepath):
            print(f"No hint file found at {filepath}, starting from scratch")
            return
        with open(filepath, 'r') as f:
            hints = json.load(f)
        loaded = 0
        skipped = 0
        for suffix, start_val in hints.items():
            if suffix in self.session_vars:
                data = self.session_vars[suffix]
                # Only add hint if the value is still in the variable's domain
                if start_val in data["allowed_starts_list"]:
                    self.model.AddHint(data["start"], start_val)
                    loaded += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        print(f"Loaded {loaded} hints, skipped {skipped} (session removed or slot no longer valid)")

    def solve(self, timeout_seconds: int = 60, solution_hint_file: str = None,
              metadata_file: str = None, seed: int = None):
        import time as time_module
        # 1. Initialize the solver
        cp_solver = cp_model.CpSolver()
        cp_solver.parameters.max_time_in_seconds = timeout_seconds
        cp_solver.parameters.log_search_progress = True
        cp_solver.parameters.exploit_best_solution = True
        if seed is not None:
            cp_solver.parameters.random_seed = seed
            print(f"Using seed: {seed}")
        else:
            seed = int(time_module.time()) % 2**31
            cp_solver.parameters.random_seed = seed
            print(f"Using random seed: {seed}")
        if self.penalties:
            self.model.Minimize(sum(self.penalties))
        print(f"Num variables: {len(self.model.Proto().variables)}")
        print(f"Num constraints: {len(self.model.Proto().constraints)}")
        # 2. Run the solver with progress tracker
        tracker = SolutionProgressTracker(self.session_vars, solution_hint_file)
        status = cp_solver.Solve(self.model, tracker)
        # 3. Handle results        
        # #print(f"Model has {len(self.model.Proto().constraints)} constraints before solving")
        
        # 3. Handle results
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.report_meeting_violations(cp_solver)
            self.report_hardwall_violations(cp_solver)
            #self.print_free_slots(cp_solver, "CLASSROOM")
            #self.print_clustering_audit(cp_solver, "BSCBIO24")
            print(f"Solution found! (Status: {cp_solver.StatusName(status)})")
            print("\n" + "="*40)
            print("      ALIGNMENT AUDIT REPORT")
            print("="*40)
            
            successful = 0
            failed = 0
            failed_groups = []
            
            for conflict in self.conflicts:
                if conflict["type"] == "SECTION_ALIGNMENT":
                    is_misaligned = cp_solver.BooleanValue(conflict["var"])
                    if is_misaligned:
                        failed += 1
                        failed_groups.append(conflict["sections"][0])
                    else:
                        successful += 1

                elif conflict["type"].startswith("CONSTRAINED"):
                    is_aligned = cp_solver.BooleanValue(conflict["var"])
                    if not is_aligned:
                        print(f"❌ CATEGORY CONFLICT: Category {conflict['type']} "
                            f"sessions {conflict['sections']} are NOT in the same slot.")

                elif conflict["type"] == "CRITICAL_MANDATORY_OVERLAP":
                    if not cp_solver.BooleanValue(conflict["var"]):
                        s1_id, s2_id = conflict["sections"]
                        print(f"❌ COHORT {conflict['cohort']}: Overlap between {s1_id} and {s2_id}")
                elif conflict["type"] == "FACULTY_B2B":
                    if cp_solver.BooleanValue(conflict["var"]):
                        f = self.scenario.get_faculty_by_id(conflict["faculty_id"])
                        print(f"❌ Faculty back to back class violation: {f.id} has back to back classes starting with {conflict['first_suffix']} starting at session {conflict['first_start']}")
                elif  conflict["type"] == "PREFERRED_THEORY_BUILDING":
                    print(f"❌ Preferred theory building violation: Section {conflict["section_id"]} requested for buildings {conflict["requested_buildings"]} but was allocated {conflict["alloted_building"]}")
                elif  conflict["type"] == "PREFERRED_LAB_BUILDING":
                    print(f"❌ Preferred lab building violation: Section {conflict["section_id"]} requested for buildings {conflict["requested_buildings"]} but was allocated {conflict["alloted_building"]}")                    
                elif  conflict["type"] == "PREFERRED_THEORY_LAYOUTS":
                    print(f"❌ Preferred theory layout violation: Section {conflict["section_id"]} requested for layouts {conflict["requested_layouts"]} but was allocated {conflict["alloted_layouts"]}")
                elif  conflict["type"] == "PREFERRED_LAB_LAYOUTS":
                    print(f"❌ Preferred lab layout violation: Section {conflict["section_id"]} requested for layouts {conflict["requested_layouts"]} but was allocated {conflict["alloted_layouts"]}")                    

            print(f"Total Aligned Section Pairs:     {successful}")
            print(f"Total Misaligned Section Pairs:  {failed}")

            if failed_groups:
                print("\nMisaligned Groups:")
                # Parse group_key back into readable form
                # group_key format: {course_id}_{s_type}_{session_index}_pair_{i}_{j}
                # e.g. BIO-136-2.00_THEORY_0_pair_0_1
                seen_groups = set()
                for group_label in failed_groups:
                    # Strip the _pair_{i}_{j} suffix to get the group key
                    parts = group_label.rsplit('_pair_', 1)
                    group_key = parts[0] if len(parts) == 2 else group_label
                    pair_info = parts[1] if len(parts) == 2 else ""
                    
                    # Parse group_key: {course_id}_{s_type}_{session_index}
                    # Split from right to get session_index and s_type
                    key_parts = group_key.rsplit('_', 2)
                    if len(key_parts) == 3:
                        course_id, s_type, session_idx = key_parts
                        label = f"{course_id} | {s_type} | Session {session_idx}"
                    else:
                        label = group_key
                        
                    if group_key not in seen_groups:
                        seen_groups.add(group_key)
                        print(f"  📌 {label} — sections not all in same slot")
                    
                    # Show the specific pair
                    if pair_info:
                        i, j = pair_info.split('_')
                        print(f"       Section pair ({i}, {j}) misaligned")

            print("="*40)
            # Save metadata for next run
            if metadata_file is not None:
                import json
                stalled = tracker.is_stalled()
                meta = {
                    "stalled": stalled,
                    "best_objective": tracker._best_objective,
                    "solutions_found": len(tracker._solutions),
                    "seed_used": seed
                }
                with open(metadata_file, 'w') as f:
                    json.dump(meta, f, indent=2)
                print(f"{'⚠️ Stalled' if stalled else '✅ Still improving'} — metadata saved")
            return self._extract_solution(cp_solver)            
        elif status == cp_model.INFEASIBLE:
            print("No solution possible with these constraints.")
        elif status == cp_model.MODEL_INVALID:
            print("Model is invalid. Check variable domains and constraints.")
        else:
            print("Solver timed out without finding a solution.")
        return None

    def report_hardwall_violations(self, solver):
        print("\n--- HARD WALL VIOLATION REPORT ---")
        violations_found = 0
        for v_data in getattr(self, 'hard_wall_violations', []):
            if solver.Value(v_data['var']) == 1:
                violations_found += 1
                print(f"CONFLICT FOR Cohort {v_data['cohort']} at Slot {v_data['slot']}:")
                print(f"  -> Cannot schedule '{v_data['unit_1']}' and '{v_data['unit_2']}' at the same time, but was forced to.")
        
        if violations_found == 0:
            print("No hard wall conflicts found! The schedule is clean.")
        else:
            print(f"Total inescapable conflicts: {violations_found}")

    def _extract_solution(self, solver):
        timetable_output = []
        for suffix, data in self.session_vars.items():
            # You must use solver.Value() to get the actual result!
            start_val = solver.Value(data["start"])
            
            assigned_room = "No Room"
            # Find which room was actually chosen
            for room_id, pres_var in data["presence_map"].items():
                if solver.BooleanValue(pres_var): # BooleanValue for BoolVars
                    assigned_room = room_id
                    break
            
            timetable_output.append({
                "section": data["section"],
                "section_id": suffix,
                "day_index": start_val // self.slots_per_day,
                "slot_index": start_val % self.slots_per_day,
                "room_id": assigned_room,
                "duration": data["duration"]
            })
        return timetable_output
    
    def print_clustering_audit(self, cp_solver, target_cohort):
        """
        Args:
            cp_solver: The solver instance returned by cp_model.CpSolver() after Solve()
            target_cohort: String name of the cohort to inspect
        """
        target_cohort = target_cohort.strip().upper()
        print(f"\n{'='*20} CLUSTERING AUDIT: {target_cohort} {'='*20}")
        
        cat_usage = {}
        
        for suffix, data in self.session_vars.items():
            section_cohorts = [c.strip().upper() for c in data["section"].eligible_cohorts]
            if target_cohort not in section_cohorts:
                continue
                
            cat = self.scenario.get_course_category_by_id(data["section"].category_id)
            if not cat or cat.choice_type.upper() != "CONSTRAINED":
                continue
                
            # FIX: Use the cp_solver object, not 'self'
            start_val = cp_solver.Value(data["start"])
            duration = data["duration"]
            slots = list(range(start_val, start_val + duration))
            
            if cat.id not in cat_usage:
                cat_usage[cat.id] = set()
            cat_usage[cat.id].update(slots)
            
            print(f"Course: {data['section'].course_id:<12} | Cat: {cat.id:<6} | Slots: {slots}")

        print("\nPER-CATEGORY SLOT FOOTPRINT:")
        for cat_id, slots in cat_usage.items():
            print(f"  📂 {cat_id}: {len(slots)} total slots -> {sorted(list(slots))}")
    
    def print_free_slots(self, solver, room_type_filter="BOTH"):
        """
        Prints free slots categorized by Room Type AND Room Size (Capacity).
        Summarizes usage for the Regular Work Week (Mon-Fri, Slots 1-4).
        """
        print("\n" + "="*85)
        print(f"      FREE SLOTS REPORT (Filter: {room_type_filter.upper()})")
        print("="*85)

        # 1. Map occupied slots
        occupied_slots = {loc.id: set() for loc in self.scenario.locations}
        for suffix, data in self.session_vars.items():
            start_val = solver.Value(data["start"])
            duration = data["duration"]
            assigned_room = next((r_id for r_id, p in data["presence_map"].items() if solver.Value(p)), None)
            if assigned_room:
                for d in range(duration):
                    t_curr = start_val + d
                    occupied_slots[assigned_room].add((t_curr // self.slots_per_day, t_curr % self.slots_per_day))

        # 2. Tracking: Combined Type + Size
        # Key format: (RoomType, Capacity)
        stats = {}
        
        days_list = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        filter_mode = room_type_filter.upper()

        for loc in self.scenario.locations:
            l_type = loc.type.upper()
            l_cap = loc.classroom_capacity
            stats_key = (l_type, l_cap)

            if stats_key not in stats:
                stats[stats_key] = {"reg_f": 0, "reg_t": 0, "sys_f": 0, "sys_t": 0, "rooms": 0}
            
            stats[stats_key]["rooms"] += 1
            room_free_slots = []
            
            for d_idx in range(self.num_days):
                day_name = days_list[d_idx] if d_idx < len(days_list) else f"Day {d_idx}"
                for s_idx in range(self.slots_per_day):
                    is_free = (d_idx, s_idx) not in occupied_slots[loc.id]
                    
                    # Global System Stats
                    stats[stats_key]["sys_t"] += 1
                    if is_free: stats[stats_key]["sys_f"] += 1

                    # --- REGULAR WORK WEEK LOGIC (Mon-Fri: 0-4, Slots: 1-4) ---
                    if d_idx <= 4 and 1 <= s_idx <= 4:
                        stats[stats_key]["reg_t"] += 1
                        if is_free: 
                            stats[stats_key]["reg_f"] += 1
                            if filter_mode == "BOTH" or filter_mode == l_type:
                                room_free_slots.append((day_name, s_idx))

            if (filter_mode == "BOTH" or filter_mode == l_type) and room_free_slots:
                print(f"\n[Room: {loc.id} | Type: {l_type} | Capacity: {l_cap}]")
                current_day = ""
                day_slots = []
                for d_name, s_val in room_free_slots:
                    if d_name != current_day:
                        if day_slots: print(f"    {current_day.ljust(5)}: Slots {', '.join(day_slots)}")
                        current_day = d_name
                        day_slots = [str(s_val)]
                    else:
                        day_slots.append(str(s_val))
                if day_slots: print(f"    {current_day.ljust(5)}: Slots {', '.join(day_slots)}")

        # 3. Consolidated Report with Size Breakdown
        print("\n" + "="*85)
        print("                CONSOLIDATED CAPACITY REPORT (TYPE & SIZE)")
        print("-" * 85)
        header = f"{'ROOM TYPE'.ljust(12)} | {'SIZE'.rjust(5)} | {'RMS'.rjust(3)} | {'REGULAR (M-F, 1-4)'.center(20)} | {'FULL SYSTEM'.center(20)}"
        print(header)
        print(f"{''.ljust(12)} | {''.rjust(5)} | {''.rjust(3)} | {'FREE/TOTAL'.center(10)} {'USAGE%'.rjust(8)} | {'FREE/TOTAL'.center(10)} {'USAGE%'.rjust(8)}")
        print("-" * 85)
        
        # Sort by Type, then by Capacity
        sorted_keys = sorted(stats.keys(), key=lambda x: (x[0], x[1]))
        
        for r_type, r_cap in sorted_keys:
            d = stats[(r_type, r_cap)]
            
            reg_u = ((d['reg_t'] - d['reg_f']) / d['reg_t'] * 100) if d['reg_t'] > 0 else 0
            sys_u = ((d['sys_t'] - d['sys_f']) / d['sys_t'] * 100) if d['sys_t'] > 0 else 0
            
            reg_str = f"{d['reg_f']}/{d['reg_t']}".center(10)
            sys_str = f"{d['sys_f']}/{d['sys_t']}".center(10)
            
            row = f"{r_type.ljust(12)} | {str(r_cap).rjust(5)} | {str(d['rooms']).rjust(3)} | {reg_str} {reg_u:>7.1f}% | {sys_str} {sys_u:>7.1f}%"
            print(row)

        print("-" * 85)
        # Totals
        total_reg_t = sum(v["reg_t"] for v in stats.values())
        total_reg_f = sum(v["reg_f"] for v in stats.values())
        total_sys_t = sum(v["sys_t"] for v in stats.values())
        total_sys_f = sum(v["sys_f"] for v in stats.values())
        
        total_reg_u = ((total_reg_t - total_reg_f) / total_reg_t * 100) if total_reg_t > 0 else 0
        total_sys_u = ((total_sys_t - total_sys_f) / total_sys_t * 100) if total_sys_t > 0 else 0

        footer = f"{'OVERALL'.ljust(12)} | {'-'.rjust(5)} | {str(len(self.scenario.locations)).rjust(3)} | {str(total_reg_f)+'/'+str(total_reg_t):^10} {total_reg_u:>7.1f}% | {str(total_sys_f)+'/'+str(total_sys_t):^10} {total_sys_u:>7.1f}%"
        print(footer)
        print("="*85 + "\n")