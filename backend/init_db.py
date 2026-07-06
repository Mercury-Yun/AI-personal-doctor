from . import models
from .database import engine


def init_db():
    models.Base.metadata.create_all(bind=engine)
    print("SQLite database initialized: ai_doctor.db")


if __name__ == "__main__":
    init_db()
