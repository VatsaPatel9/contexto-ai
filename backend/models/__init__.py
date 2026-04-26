"""Import all ORM models so that Base.metadata is fully populated."""

from backend.models.conversation import Conversation, Message  # noqa: F401
from backend.models.dataset import Dataset, Document, DocumentSegment  # noqa: F401
from backend.models.user_course import UserCourse  # noqa: F401
from backend.models.user_flags import UserFlag  # noqa: F401
