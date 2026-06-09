import pandas as pd
import numpy as np
import sys
from pprint import PrettyPrinter
from typing import List, Tuple, Dict, Set
from .domain import (
    TimetableScenario, WorkWeekConfig, TeachingLocation, Faculty, 
    Course, Section, Cohort, RoomType,  TimeSlot, CourseCategory,
    Program, Term
)

class ExcelDataLoader:

    def __init__(self, file_path: str):
        self.file_path = file_path
        # We load the whole file once to access different sheets
        self.xls = pd.ExcelFile(file_path)

    def _load_categories(self) -> List[CourseCategory]:
        df_cat = pd.read_excel(self.xls, 'Categories').replace({np.nan: None})
        categories = []
        #print(df_cat)
        for _, row in df_cat.iterrows():
            # Parse allowed_days: "1,2,3,4" -> [1, 2, 3, 4]
            raw_days = str(row['allowed_days']).strip() if row.get('allowed_days') else None
            allowed_days = [int(x.strip()) for x in raw_days.split(',')] if raw_days and raw_days != "None" else None

            # Parse allowed_slots: "1,2,3,4" -> [1, 2, 3, 4]
            raw_slots = str(row['allowed_slots']).strip() if row.get('allowed_slots') else None
            allowed_slots = [int(x.strip()) for x in raw_slots.split(',')] if raw_slots and raw_slots != "None" else None

            raw_pref = str(row['preferred_slot']).strip() if row.get('preferred_slot') else None
            preferred = [int(x.strip()) for x in raw_pref.split(',')] if raw_pref and raw_pref != "None" else []            
            #print(row["choice_type"], type(row["choice_type"]))
            categories.append(CourseCategory(
                id=str(row['ID']), 
                name=str(row['Name']), 
                choice_type=row['choice_type'].upper()  if row['choice_type'] is not None else "NONE",
                choice_count=int(row['choice_count']) if row['choice_count'] is not None else 0,
                allowed_slots=allowed_slots,
                allowed_days=allowed_days,
                preferred_slots=preferred
            ))
        #sys.exit(0)
        return categories

    def _load_locations(self) -> List[TeachingLocation]:
        # 1. Load Rooms
        df_rooms = pd.read_excel(self.xls, 'Rooms').replace({np.nan: None})
        # print(df_rooms)
        print("Loading rooms")
        # for _, row in df_rooms.iterrows():
        #     print(row)
        locations = []
        for _, row in df_rooms.iterrows():
            building = str(row['building']).strip().upper() if row.get('building') else None

            raw_layouts = str(row['layouts']).strip().upper() if row.get('layouts') else None
            layouts = [l.strip().upper() for l in raw_layouts.split(',')] if raw_layouts and raw_layouts != "None" else None

            locations.append(
                TeachingLocation(
                    id=str(row['id']), name=str(row['name']), 
                    type=RoomType(row['type']),
                    classroom_capacity=row['classroom_capacity'],
                    building=building,
                    layouts = layouts,
                    lab_type=row['lab_type'].strip().upper() if row['lab_type'] else None
                )
            )

        # Checks. Basic individual checks done in pydantic. Do cumulative checks here
        # Check for duplicate room IDs
        l_list = [l.id for l in locations]
        l_set = set(l_list)
        if len(list(l_set)) != len(l_list):
            print("Duplicate locations found! Exiting.")
            return None        
        return locations

    def _load_programs(self, config: WorkWeekConfig) -> List[Program]:
        print("Loading programs")
        df_programs = pd.read_excel(self.xls, 'Programs').replace({np.nan: None})
        programs = []
       
        for _, row in df_programs.iterrows():
            #print(row['meeting_slots'], type(row['meeting_slots']))
            meeting_slots_str = str(row['meeting_slots']).strip()
            if meeting_slots_str and meeting_slots_str.lower() not in ('none', 'nan'):
                meeting_slots = [int(float(x.strip())) for x in meeting_slots_str.split(',')]
            else:
                meeting_slots = []
            programs.append(
                Program(program_id=str(row['program_id'].strip().upper()), 
                        program_name=str(row['program_name']), 
                        meeting_slots=meeting_slots
                )
            )
        return programs
    
    def _load_terms(self) -> List[Term]:
        from datetime import date
        try:
            df = pd.read_excel(self.xls, 'Terms').replace({np.nan: None})
            terms = []
            for _, row in df.iterrows():
                term_id = str(row['term_id']).strip()
                start = pd.to_datetime(row['start_date']).date()
                end = pd.to_datetime(row['end_date']).date()
                terms.append(Term(term_id=term_id, start_date=start, end_date=end))
            print(f"Loaded {len(terms)} terms: {[t.term_id for t in terms]}")
            return terms
        except Exception:
            print("No Terms sheet found — deriving FULL term from section dates")
            try:
                df_sec = pd.read_excel(self.xls, 'Sections').replace({np.nan: None})
                start_dates = pd.to_datetime(df_sec['Start date'].dropna()).dt.date
                end_dates = pd.to_datetime(df_sec['End date'].dropna()).dt.date
                term_start = min(start_dates)
                term_end = max(end_dates)
            except Exception:
                term_start = date(date.today().year, 1, 1)
                term_end = date(date.today().year, 12, 31)
                print("Could not derive term dates from sections — using calendar year defaults")
            return [Term(term_id="FULL", start_date=term_start, end_date=term_end)]
    

    def _load_faculty(self, config: WorkWeekConfig) -> List[Faculty]:
        # 2. Load Faculty
        print("Loading faculty")
        df_fac = pd.read_excel(self.xls, 'Faculty').replace({np.nan: None})
        faculty = []
        for _, row in df_fac.iterrows():
            #print(row)
            available_slots = []
            for i, day in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']):
                avail_list = str(row[day]).strip().split(',')
                for a in avail_list:
                    if a.strip() == 'ALL':
                        for s in range(config.slots_per_day):
                            available_slots.append(TimeSlot(day_index=i, slot_index=s))
                    elif a.strip() != 'NONE':
                        available_slots.append(TimeSlot(day_index=i, slot_index=int(a.strip())))
            faculty.append(
                Faculty(id=str(row['id']).strip().lower(), name=str(row['name']), 
                        available_slots=available_slots)
            )
        # Checks. Basic individual checks done in pydantic. Do cumulative checks here
        # Check for duplicate room IDs
        faculty_id_list = [f.id for f in faculty]
        duplicates = [f for f in set(faculty_id_list) if faculty_id_list.count(f) > 1]
        if duplicates:
            print(f"Duplicate faculty {','.join(duplicates)} found! Exiting.")
            return None
        return faculty

    def _load_courses_sections_cohorts(self, faculty: List[Faculty], course_categories: List[CourseCategory], programs: List[Program]) -> Tuple[List[Course], List[Section], Set]:
        # 3. Load Merged Sections with "ALL" and Duration logic
        try:
            df_sections = pd.read_excel(self.xls, 'Sections').replace({np.nan: None})
            courses = []
            sections = []
            explicit_cohort_ids = set()
            print("Loading courses and sections")
            courses_map = {} # To ensure uniqueness
            for _, row in df_sections.iterrows():
                # print(row)
                course_code = str(row['course_code']).strip()
                category_id = str(row['category']).strip()
                program_ids_str = str(row['program_ids']).strip()
                if program_ids_str != '':
                    program_ids_set = {c.upper().strip() for c in program_ids_str.split(',')}
                    program_ids = list(program_ids_set)
                else:   
                    program_ids = []
                if programs and program_ids:
                    all_program_ids = {p.program_id.upper().strip() for p in programs}
                    if not program_ids_set.issubset(all_program_ids):
                        print(f"Unknown program ID found in section {course_code}__Section_{int(row['section_number'])}. IGNORING")
                course_category = None
                for c in course_categories:
                    if c.id.lower().strip() == category_id.lower().strip():
                        course_category = c
                        break
                if course_category is None:
                    # Unknown category so dont load this course
                    print(f"UNKNOWN COURSE CATEGORY {category_id} FOUND! Exiting!")
                    sys.exit(0)
                
                # 1. Parse Cohorts for this SPECIFIC Section
                cohort_str = str(row['cohorts']).upper().strip()
                if cohort_str.upper() == "ALL":
                    section_cohorts = ["ALL"]
                else:
                    section_cohorts = [c.upper().strip() for c in cohort_str.split(',')]
                    explicit_cohort_ids.update(section_cohorts)

                
                # 2. Handle the Course object (Create ONLY if it doesn't exist)
                if course_code not in courses_map:
                    courses_map[course_code] = Course(
                        id=course_code, # Correct variable reference
                        name=str(row['course_name']).strip(),
                        theory_durations=[int(float(d.strip())) for d in str(row['theory_durations']).split(',') if (d and d.strip())]
                                    if pd.notna(row['theory_durations']) and str(row['theory_durations']).strip() != "" else [],
                        lab_durations=[int(float(d.strip())) for d in str(row['lab_durations']).split(',') if d.strip()] 
                                    if pd.notna(row['lab_durations']) and str(row['lab_durations']).strip() != "" else [],
                        required_classroom_size=row['required_room_capacity'],
                        required_lab_type=row['required_lab_type'].strip().upper() if pd.notna(row['required_lab_type']) else None,
                        program_ids=program_ids,
                    )
                # 3. Create the Section
                # Generate ID: e.g., CS101__Section_1
                section_id = f"{course_code}__Section_{int(row['section_number'])}"
                raw_slots = str(row['allowed_slots']).strip() if row.get('allowed_slots') else None
                sec_slots_allowed = [int(x.strip()) for x in raw_slots.split(',')] if raw_slots and raw_slots != "None" else None

                raw_days = str(row['allowed_days']).strip() if row.get('allowed_days') else None
                sec_days_allowed = [int(x.strip()) for x in raw_days.split(',')] if raw_days and raw_days != "None" else None                

                raw_pref_slot = str(row['preferred_slot']).strip() if row.get('preferred_slot') else None
                sec_preferred = [int(x.strip()) for x in raw_pref_slot.split(',')] if raw_pref_slot and raw_pref_slot != "None" else []
                
                term_id = str(row['term_id']).strip().upper() if row.get('term_id') and pd.notna(row.get('term_id')) else "FULL"
                
                raw_preferred_theory_buildings = str(row['preferred_theory_buildings']).strip().upper() if row.get('preferred_theory_buildings') else None
                preferred_theory_buildings = [b.strip().upper() for b in raw_preferred_theory_buildings.split(',')] if raw_preferred_theory_buildings and raw_preferred_theory_buildings != "None" else None

                raw_preferred_lab_buildings = str(row['preferred_lab_buildings']).strip().upper() if row.get('preferred_lab_buildings') else None
                preferred_lab_buildings = [b.strip().upper() for b in raw_preferred_lab_buildings.split(',')] if raw_preferred_lab_buildings and raw_preferred_lab_buildings != "None" else None                

                raw_preferred_theory_layouts = str(row['preferred_theory_layouts']).strip().upper() if row.get('preferred_theory_layouts') else None
                preferred_theory_layouts = [l.strip().upper() for l in raw_preferred_theory_layouts.split(',')] if raw_preferred_theory_layouts and raw_preferred_theory_layouts != "None" else None

                raw_preferred_lab_layouts = str(row['preferred_lab_layouts']).strip().upper() if row.get('preferred_lab_layouts') else None
                preferred_lab_layouts = [l.strip().upper() for l in raw_preferred_lab_layouts.split(',')] if raw_preferred_lab_layouts and raw_preferred_lab_layouts != "None" else None

                sections.append(Section(
                    id=section_id, 
                    course_id=course_code,
                    category_id=str(row['category']).strip(),
                    faculty_ids=[f.strip().lower() for f in str(row['faculty_id']).split(',') if f.strip()],
                    eligible_cohorts=section_cohorts,
                    allowed_slots=sec_slots_allowed,
                    preferred_theory_buildings=preferred_theory_buildings,
                    preferred_lab_buildings=preferred_lab_buildings,
                    preferred_theory_layouts = preferred_theory_layouts,
                    preferred_lab_layouts = preferred_lab_layouts,
                    allowed_days=sec_days_allowed,
                    preferred_slots=sec_preferred,
                    term_id=term_id
                ))
            # # Final list of unique courses
            faculty_id_list = [f.id.strip().lower() for f in faculty]        
            courses = list(courses_map.values())
            unknown_faculty_list = set()
            for s in sections:
                course_category = None
                for c in course_categories:
                    if c.id.lower().strip() == s.category_id.lower().strip():
                        course_category = c
                        break
                # Dont check faculty for the VIRTUAL_OPEN choice_type
                if course_category is None or course_category.choice_type.upper()  == 'VIRTUAL_OPEN':
                    continue
                for fid in s.faculty_ids:
                    if fid.strip().lower() not in faculty_id_list:
                        unknown_faculty_list.add(fid)
            if unknown_faculty_list:
                    print(f"The following unknown faculty IDs {','.join(unknown_faculty_list)} were specified in the sections tab. Exiting.")
                    return None, None, None

            return courses, sections, explicit_cohort_ids
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            print(f"Error loading Excel file: {str(e)}")
            return None, None, None

    def _get_course_by_id(self, courses, course_id: str) -> Course:
        for c in courses:
            if c.id == course_id:
                return c
        return None

    def load_scenario(self, config: WorkWeekConfig) -> TimetableScenario:
        pp = PrettyPrinter(indent=4)

        categories = self._load_categories()
        if not categories:
            print("No categories found! Exiting.")
            return None
        #pp.pprint(categories)

        locations = self._load_locations()
        if not locations:
            print("No locations found! Exiting.")
            return None
        #pp.pprint(locations)
        
        faculty = self._load_faculty(config)
        if not faculty:
            print("No faculty found! Exiting.")
            return None
        #pp.pprint(faculty)

        programs = self._load_programs(config)
        if not programs:
            print("No programs found! Exiting.")
            return None
        #pp.pprint(programs)

        terms = self._load_terms()
        if not terms:
            print("No terms found! Exiting.")
            return None
        #pp.pprint(terms)
        
        courses, sections, cohorts = self._load_courses_sections_cohorts(faculty, categories, programs)
        if not courses or not sections:
            print("No courses or sections found! Exiting.")
            return None
        # pp.pprint(courses)
        # pp.pprint(sections)
        
        #category_map = self._load_category_slots(config)
        # pp.pprint(category_map)        
        #if not category_map:
        #    return None

        
        #config.category_slots = category_map

        print("\n--- PRE-SOLVE DATA VALIDATION ---")
        #if not self._validate_data(config, locations, faculty, courses, sections, category_map):
        if not self._validate_data(config, locations, faculty, courses, sections, categories):
            print("Data validation failed! Exiting.")
            return None
        
        return TimetableScenario(
            config=config, locations=locations, faculty=faculty, 
            courses=courses, sections=sections,
            cohorts=[Cohort(id=cid) for cid in cohorts if cid],
            course_categories=categories,
            programs=programs,
            terms=terms
        )
        
    def _validate_location_sufficiency(self, config, locations, sections, courses, course_categories) -> bool:
        print("Performing basic location sufficiency checks")
        num_labs = 0
        num_classrooms = 0
        for l in locations:
            if l.type == RoomType.LAB:
                num_labs += 1
            elif l.type == RoomType.CLASSROOM or l.type == RoomType.EITHER:
                num_classrooms += 1
        
        num_slots = config.days_per_week * config.slots_per_day
        num_lab_slots = num_labs * num_slots
        num_classroom_slots = num_classrooms * num_slots

        num_theory_slots_required = 0
        num_lab_slots_required = 0
        for s in sections:
            cat = next((c for c in [self._get_course_by_id(courses, s.course_id)] if c), None)
            if cat is None:
                continue
            # Find category for this section
            sec_cat = next((c for c in course_categories if c.id.lower().strip() == s.category_id.lower().strip()), None)
            if sec_cat and sec_cat.choice_type.upper() in ('VIRTUAL_STAFFED', 'VIRTUAL_OPEN'):
                continue  # no room needed
            num_theory_slots_required += sum(cat.theory_durations)
            num_lab_slots_required += sum(cat.lab_durations)

        check = True
        print(f"Number of classroom slots required: {num_theory_slots_required}")
        print(f"Number of classroom slots available: {num_classroom_slots}")
        print(f"Number of lab slots required: {num_lab_slots_required}")
        print(f"Number of lab slots available {num_lab_slots}")

        if num_theory_slots_required > num_classroom_slots:
            print(f"Total classroom slots required ({num_theory_slots_required}) exceeds total classroom slots ({num_classroom_slots}) ")
            check = False
        if num_lab_slots_required > num_lab_slots:
            print(f"Total lab slots required ({num_lab_slots_required}) exceeds total lab slots ({num_lab_slots}) ")
            check = False
        
        if check:
            print("Location sufficiency checks passed.")
        else:
            print("Location sufficiency checks failed.")

        return check

    def _check_category_map_validaty(self, sections, category_map):
        category_map_set = set()
        for cat_list in category_map.values():
            for cat in cat_list:
                if cat not in category_map_set:
                    category_map_set.add(cat)
        missing_categories = set()
        for s in sections:
            if s.category.lower().strip() not in category_map_set:
                missing_categories.add(s.category.lower().strip())
        if missing_categories:
            print(f"The following categories from the sections list are not present in the category slots : {','.join(list(missing_categories))}")
            return False
        
        return True

    def _check_faculty_availability(self, faculty, sections, courses):
        """Checks for data errors like workload exceeding availability or day count."""
        ret_val = True
       
        # Check Faculty capacity
        print("Checking faculty availability")
        for fac in faculty:
            needed = sum(
                sum(c.theory_durations) + sum(c.lab_durations)
                for s in sections if fac.id in s.faculty_ids
                for c in [self._get_course_by_id(courses, s.course_id)]
            )
            available = len(fac.available_slots)
            if needed > available:
                print(f"CONFLICT: {fac.name} assigned {needed} slots but only has {available} available.")
                ret_val = False
        if ret_val == True:
            print("Faculty availability check passed.")
        else:
            print("Faculty availability check failed.")
        return ret_val

    def _check_course_day_separation(self, config, faculty, sections, courses):
        ret_val = True
        # Check Day Separation (Max 1 session of same course per day)
        print("Checking day separation")
        num_days = config.days_per_week
        for course in courses:
            total_sessions = len(course.theory_durations) + len(course.lab_durations)
            if total_sessions > num_days:
                print(f"CONFLICT: {course.name} has {total_sessions} sessions but week only has {num_days} days.")
                ret_val = False
        if ret_val == True:
            print("Day separation check passed.")
        else:
            print("Day separation check failed.")
        return ret_val

    #def _validate_data(self, config: WorkWeekConfig, locations: List[TeachingLocation], faculty: List[Faculty], courses: List[Course], sections: List[Section], category_map: Dict[TimeSlot, List[str]]):
    def _validate_data(self, config: WorkWeekConfig, locations: List[TeachingLocation], faculty: List[Faculty], courses: List[Course], sections: List[Section], course_categories: List[CourseCategory]):
        vl = self._validate_location_sufficiency(config, locations, sections, courses, course_categories)
        vfa = self._check_faculty_availability(faculty, sections, courses)
        #cm_ok = self._check_category_map_validaty(sections, category_map)
        #if vl and vfa and cm_ok:
        if vl and vfa:
            return True
        return False


    
    # def _load_category_slots(self, config) -> Dict[TimeSlot, List[str]]:
    #     print("Loading categories")
    #     # 4. Load Category Slots
    #     df_cat = pd.read_excel(self.xls, 'Category_Slots')
    #     day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    #     category_map = {}
    #     slots_taken = []
    #     for day in range(config.days_per_week):
    #         slots_taken.append([])
    #         for slot in range(config.slots_per_day):
    #             slots_taken[day].append(False)

    #     for _, row in df_cat.iterrows():
    #         day = str(row['day']).strip()
    #         if day not in day_map:
    #             print("Invalid day value {day} in Category Slots. Exiting.")
    #             return None
    #         slot_index = int(row['slot_index'])
    #         if slot_index < 0 or slot_index >= config.slots_per_day:
    #             print(f"Invalid slot index {slot_index} in Category Slots. Exiting.")
    #             return None
            
    #         orig_cat_list = str(row['Category']).strip().split(',')
    #         cat_list = [c.lower().strip() for c in orig_cat_list if c.strip()]
    #         if slots_taken[day_map[day]][slot_index]:
    #             print(f"Day {day}, Slot {slot_index} is repreated in Category Slots. Exiting.")
    #             return None
    #         else:
    #             slots_taken[day_map[day]][slot_index] = True
    #             category_map[TimeSlot(day_index = day_map[day], slot_index = slot_index)] = cat_list
    #     return category_map    

    # def _parse_available_slots(self, day_str: str, config: WorkWeekConfig) -> List[TimeSlot]:
    # """Converts a string like 'Mon, Tue' into a list of all TimeSlots for those days."""
    # day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    # days = [day_map[d.strip()] for d in day_str.split(',') if d.strip() in day_map]
    
    # slots = []
    # for d in days:
    #     for s in range(config.slots_per_day):
    #         slots.append(TimeSlot(day_index=d, slot_index=s))
    # return slots