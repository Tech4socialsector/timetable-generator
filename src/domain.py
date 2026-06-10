from enum import Enum
from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import date

# --- ENUMS (Restricting Choices) ---

class RoomType(str, Enum):
    CLASSROOM = "CLASSROOM"
    LAB = "LAB"
    EITHER = "EITHER"
    @classmethod
    def _missing_(cls, value):
        if value == "" or value is None:
            return cls.EITHER        
        return super()._missing_(value)


class LabType(str, Enum):
    COMPUTER = "COMPUTER LAB".capitalize()
    PHYSICS = "PHYSICS".capitalize()
    CHEMISTRY = "CHEMISTRY LAB".capitalize()
    BIOLOGY = "BIOLOGY LAB".capitalize()
    DANCE = "DANCE".capitalize()
    ELECTRONIC = "ELECTRONICS".capitalize()
    ESS = "ESS"
    MATHS = "MATH".capitalize()
    MUSIC = "MUSIC".capitalize()
    OPEN_SPACE = "Open space".capitalize()
    SHED = "SHED".capitalize()
    SPORTS_COMPLEX = "Sports complex".capitalize()
    SPORTS_FIELD = "Sports Field".capitalize()
    THEATRE = "THEATRE".capitalize()
    TE = "TE"
    NONE = "NONE"  # For normal classrooms
    @classmethod
    def _missing_(cls, value):
        if value == "" or value is None:
            return cls.NONE
        return super()._missing_(value)    

# --- CORE VALUE OBJECTS ---

class TimeSlot(BaseModel):
    """Represents a specific time block in the week."""
    day_index: int = Field(..., ge=0, description="0=Monday, 1=Tuesday, etc.")
    slot_index: int = Field(..., ge=0, description="0=08:00, 1=09:00, etc.")

    class Config:
        frozen = True # Makes this hashable so we can use it in sets

class Programme(BaseModel):
    id: str
    name: str
    duration_years: int

class Major(BaseModel):
    # Example Biology/Chemistry, etc
    id: str
    name: str

class Cohort(BaseModel):
    """Represents a specific student group"""
    id: str

class TeachingLocation(BaseModel):
    id: str = Field(..., description="Unique Room ID, e.g., RM_101")
    name: str
    building: str
    type: RoomType
    # Optional subtypes: validation ensures correct pairing below
    classroom_capacity: Optional[int] = None
    lab_type: Optional[str] = None
    layouts: Optional[List[str]] = None
    available_slots: List[TimeSlot]

    @model_validator(mode='after')
    def validate_subtypes(self):
        if self.type == RoomType.CLASSROOM and self.classroom_capacity == None:
            raise ValueError("Classrooms must have a size")
        if self.type == RoomType.LAB and self.lab_type is None:
            raise ValueError("Labs must be specified")
        if self.type == RoomType.EITHER and (self.lab_type is None or self.classroom_capacity == None):
            raise ValueError("Locations marked 'EITHER' must have a specific lab type and a classroom capacity")
        return self

class Faculty(BaseModel):
    id: str = Field(..., description="Unique Faculty ID, e.g., EMP001")
    name: str
    # List of specific slots this faculty is available
    available_slots: List[TimeSlot]

class Program(BaseModel):
    """Represents a scheduled meeting or blocked time for faculty/rooms."""
    program_id: str
    program_name: str
    meeting_slots: List[int] = []

class Term(BaseModel):
    """Represents a sub-term or full term period within the academic year."""
    term_id: str
    start_date: date
    end_date: date

    def overlaps(self, other: 'Term') -> bool:
        return self.start_date <= other.end_date and other.start_date <= self.end_date
# --- CONFIGURATION MODELS ---

class WorkWeekConfig(BaseModel):
    days_per_week: int = 6
    slots_per_day: int = 6
    lunch_slots: List[int]
    meeting_slots: List[TimeSlot]
    # NEW: Maps "Category Name" to preferred slots
    category_slots: Dict[TimeSlot, List[str]] = {} 

    @field_validator('lunch_slots')
    def validate_contiguous_lunch(cls, v):
        if not v:
            return v
        sorted_slots = sorted(v)
        # Check if slots are strictly sequential (e.g., 3, 4, 5)
        for i in range(len(sorted_slots) - 1):
            if sorted_slots[i+1] != sorted_slots[i] + 1:
                raise ValueError(f"Lunch slots must be contiguous. Got {v}")
        return v

# --- COURSE & SECTIONS ---

class CourseCategory(BaseModel):
    id: str
    name: str
    choice_type: Literal['NONE', 'CONSTRAINED', 'COMPLETE', 'GROUPED', 'VIRTUAL_STAFFED', 'VIRTUAL_OPEN']
    choice_count: int = 0
    allowed_slots: Optional[List[int]] = None
    allowed_days: Optional[List[int]] = None
    preferred_slots: List[int] = []

class Course(BaseModel):
    id: str = Field(..., description="Unique Course Code, e.g., CS101")
    name: str
    
    # Requirements
    theory_durations: List[int] = []
    lab_durations: List[int] = []
    
    # Room Requirements
    required_classroom_size: Optional[int] = None
    required_lab_type: Optional[str] = None

    program_ids: Optional[List[str]] = None
    
    @model_validator(mode='after')
    def validate_subtypes(self):
        if self.theory_durations == None and self.lab_duration == None:
            raise ValueError(f"Course {self.name} has neither lab_durations nor theory_durations")
        if self.required_classroom_size == None and self.required_lab_type is None:
            raise ValueError(f"Course {self.name} has neither required_classroom_size nor required_lab_type")
        return self

class Section(BaseModel):
    """
    A specific instance of a course.
    Since faculty is pre-assigned to a section, we link them here.
    """
    id: str = Field(..., description="Unique Section ID")
    course_id: str = Field(..., description="Unique Course ID")# Link back to Course
    faculty_ids: List[str] = Field(..., description="List of Faculty IDs for this section")
    preferred_theory_buildings: Optional[List[str]] = None
    preferred_lab_buildings: Optional[List[str]] = None
    preferred_theory_layouts: Optional[List[str]] = None
    preferred_lab_layouts: Optional[List[str]] = None
    eligible_cohorts: List[str]
    category_id: str = Field(..., description="Category ID")
    allowed_slots: Optional[List[int]] = None
    allowed_days: Optional[List[int]] = None
    preferred_slots: List[int] = []
    term_id: str = "FULL"
    
    @property
    def category(self) -> str:
        return self.category_id

    
    # We might need to override requirements if a specific section 
    # has special needs, but usually it inherits from Course.

class TimetableScenario(BaseModel):
    config: WorkWeekConfig
    cohorts: List[Cohort]
    faculty: List[Faculty]
    locations: List[TeachingLocation]
    courses: List[Course]
    sections: List[Section]
    programs: List[Program]
    course_categories: List[CourseCategory]
    terms: List[Term] = []


    def get_course_by_id(self, course_id: str) -> Course:
        return next(c for c in self.courses if c.id == course_id)
    
    def get_program_by_id(self, program_id: str) -> Program:
        return next((p for p in self.programs if p.program_id.strip().upper() == program_id.strip().upper()), None)
    
    def get_faculty_by_id(self, faculty_id: str) -> Faculty:
        return next((f for f in self.faculty if f.id == faculty_id), None)
    def get_section_by_id(self, section_id: str) -> Section:
            """Finds a section object by its ID string."""
            return next((s for s in self.sections if s.id == section_id), None)
    
    def get_location_by_id(self, location_id: str) -> TeachingLocation:
        for l in self.locations:
            if l.id.lower().strip() == location_id.lower().strip():
                return l
        return None
    
    def get_course_category_by_id(self, category_id: str) -> CourseCategory:
        for c in self.course_categories:
            if c.id.lower().strip() == category_id.lower().strip():
                return c
        return None
    
    def get_term_by_id(self, term_id: str) -> Optional['Term']:
        return next((t for t in self.terms if t.term_id.strip().upper() == term_id.strip().upper()), None)

    def terms_overlap(self, term_id_1: str, term_id_2: str) -> bool:
        t1 = self.get_term_by_id(term_id_1)
        t2 = self.get_term_by_id(term_id_2)
        if t1 is None or t2 is None:
            return True  # assume overlap if term not found
        return t1.overlaps(t2)    