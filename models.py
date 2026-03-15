from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from database import Base


class PuzzleSolve(Base):
    __tablename__ = "puzzle_solves"

    id = Column(Integer, primary_key=True)
    gc_code = Column(String(20), nullable=False, index=True)
    cache_name = Column(String(200))
    cache_type = Column(String(50))
    difficulty = Column(Float)
    terrain = Column(Float)
    owner = Column(String(100))
    posted_coords = Column(String(100))
    description_text = Column(Text)
    description_html = Column(Text)
    hint_decoded = Column(Text)
    image_paths = Column(Text)  # JSON array
    screenshot_path = Column(String(500))
    claude_analysis = Column(Text)
    solved_coords = Column(String(100))
    confidence = Column(Float)
    research_source_type = Column(String(50))
    research_url = Column(String(500))
    research_summary = Column(String(200))
    research_excerpt = Column(Text)
    extracted_facts_json = Column(Text)
    variable_resolution_json = Column(Text)
    structured_solution_json = Column(Text)
    solve_status = Column(String(20), default="pending")  # pending, solved, failed
    created_at = Column(DateTime, default=datetime.utcnow)
