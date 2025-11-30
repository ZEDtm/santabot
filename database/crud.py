from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Union, Dict, Any
from datetime import datetime, timedelta
from . import models, schema
from sqlalchemy import or_, and_

def get_db():
    """Dependency for getting database session"""
    db = models.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Event operations
def create_event(
    db: Session, 
    group_id: int, 
    title: str, 
    registration_end: datetime, 
    shipping_deadline: datetime,
    admin_id: int,
    group_name: Optional[str] = None,
    budget: Optional[int] = None,
    photo_id: Optional[str] = None
) -> models.Event:
    """Create a new event
    
    Args:
        db: Database session
        group_id: Telegram group chat ID
        title: Event title
        registration_end: Registration end datetime
        shipping_deadline: Shipping deadline datetime
        admin_id: Telegram user ID of the admin who created the event
        group_name: Optional name of the group chat
        budget: Optional budget for gifts
        photo_id: Optional photo file ID for the event
    """
    db_event = models.Event(
        group_id=group_id,
        admin_id=admin_id,
        group_name=group_name,
        title=title,
        photo_id=photo_id,
        registration_end=registration_end,
        shipping_deadline=shipping_deadline,
        budget=budget
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

def get_event(db: Session, event_id: int) -> Optional[models.Event]:
    """Get event by ID"""
    return db.query(models.Event).filter(models.Event.id == event_id).first()

def get_event_by_id(db: Session, event_id: int) -> Optional[models.Event]:
    """Get event by ID (alias for get_event for backward compatibility)"""
    return get_event(db, event_id)

def update_event(
    db: Session, 
    event_id: int, 
    update_data: Dict[str, Any]
) -> Optional[models.Event]:
    """Update event data"""
    db_event = get_event(db, event_id)
    if not db_event:
        return None
        
    for key, value in update_data.items():
        if hasattr(db_event, key):
            setattr(db_event, key, value)
            
    db.commit()
    db.refresh(db_event)
    return db_event

def get_events_by_group(db: Session, group_chat_id: int) -> List[models.Event]:
    """Get all events for a specific group with participants loaded"""
    return (db.query(models.Event)
            .options(joinedload(models.Event.participants))
            .filter(models.Event.group_chat_id == group_chat_id)
            .order_by(models.Event.created_at.desc())
            .all())

def get_events_by_admin(db: Session, admin_id: int) -> List[models.Event]:
    """Get all events created by a specific admin with participants loaded"""
    return (db.query(models.Event)
            .options(joinedload(models.Event.participants))
            .filter(models.Event.admin_id == admin_id)
            .order_by(models.Event.created_at.desc())
            .all())

# Participant operations
def create_participant(
    db: Session,
    event_id: int,
    telegram_id: int,
    first_name: str,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    wishes: Optional[str] = None,
    address: Optional[str] = None,
    delivery_methods: Optional[str] = None
) -> models.Participant:
    """Create a new participant"""
    db_participant = models.Participant(
        event_id=event_id,
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        wishes=wishes,
        address=address,
        delivery_methods=delivery_methods
    )
    db.add(db_participant)
    db.commit()
    db.refresh(db_participant)
    return db_participant

def get_participant(db: Session, participant_id: int) -> Optional[models.Participant]:
    """Get participant by ID"""
    return db.query(models.Participant).filter(models.Participant.id == participant_id).first()

def get_participant_by_telegram(
    db: Session, 
    event_id: int, 
    telegram_id: int
) -> Optional[models.Participant]:
    """Get participant by Telegram ID and event"""
    return db.query(models.Participant).filter(
        models.Participant.event_id == event_id,
        models.Participant.telegram_id == telegram_id
    ).first()

# Santa Pair operations
def create_santa_pair(
    db: Session,
    event_id: int,
    santa_id: int,
    receiver_id: int
) -> models.SantaPair:
    """Create a new Santa-receiver pair"""
    db_pair = models.SantaPair(
        event_id=event_id,
        santa_id=santa_id,
        receiver_id=receiver_id
    )
    db.add(db_pair)
    db.commit()
    db.refresh(db_pair)
    return db_pair

def get_santa_pair(
    db: Session,
    event_id: int,
    santa_id: int
) -> Optional[models.SantaPair]:
    """Get Santa pair by event and santa ID"""
    return db.query(models.SantaPair).filter(
        models.SantaPair.event_id == event_id,
        models.SantaPair.santa_id == santa_id
    ).first()

# Message operations
def create_anonymous_message(
    db: Session,
    pair_id: int,
    message_text: str,
    from_santa: bool = True
) -> models.AnonymousMessage:
    """Create a new anonymous message"""
    db_message = models.AnonymousMessage(
        pair_id=pair_id,
        message_text=message_text,
        from_santa=from_santa
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_messages_for_pair(
    db: Session,
    pair_id: int,
    limit: int = 50
) -> List[models.AnonymousMessage]:
    """Get message history for a Santa-receiver pair"""
    return (
        db.query(models.AnonymousMessage)
        .filter(models.AnonymousMessage.pair_id == pair_id)
        .order_by(models.AnonymousMessage.created_at.desc())
        .limit(limit)
        .all()
    )

def create_gift_confirmation(
    db: Session,
    pair_id: int,
    tracking_number: Optional[str] = None,
    message: Optional[str] = None
) -> models.GiftConfirmation:
    """Create a new gift confirmation"""
    db_confirmation = models.GiftConfirmation(
        pair_id=pair_id,
        tracking_number=tracking_number,
        message=message
    )
    db.add(db_confirmation)
    db.commit()
    db.refresh(db_confirmation)
    return db_confirmation

def get_gift_confirmations(
    db: Session,
    pair_id: int
) -> List[models.GiftConfirmation]:
    """Get all gift confirmations for a pair"""
    return (
        db.query(models.GiftConfirmation)
        .filter(models.GiftConfirmation.pair_id == pair_id)
        .order_by(models.GiftConfirmation.sent_at.desc())
        .all()
    )

def has_gift_confirmation(
    db: Session,
    pair_id: int
) -> bool:
    """Check if a gift has been confirmed for this pair"""
    return (
        db.query(models.GiftConfirmation)
        .filter(models.GiftConfirmation.pair_id == pair_id)
        .first() is not None
    )

def is_user_admin(db: Session, user_id: int) -> bool:
    """Check if user is an admin"""
    from config import settings
    return user_id in settings.ADMIN_IDS

def get_events_with_active_registration(
    db: Session,
    time_left: timedelta,
    min_time_left: Optional[timedelta] = None,
    status: Optional[str] = None
) -> List[models.Event]:
    """Get events with registration ending within the specified time range"""
    now = datetime.now()
    end_time = now + time_left
    
    query = db.query(models.Event).filter(
        models.Event.registration_end <= end_time,
        models.Event.registration_end > now - timedelta(days=1)  # Don't check events older than 1 day
    )
    
    if min_time_left:
        start_time = now + min_time_left
        query = query.filter(models.Event.registration_end >= start_time)
        
    if status:
        query = query.filter(models.Event.status == status)
        
    return (
        query
        .options(joinedload(models.Event.participants))
        .options(joinedload(models.Event.pairs).joinedload(models.SantaPair.receiver))
        .all()
    )

def get_events_with_upcoming_deadline(
    db: Session,
    time_left: timedelta,
    min_time_left: Optional[timedelta] = None,
    status: Optional[str] = None
) -> List[models.Event]:
    """Get events with shipping deadline within the specified time range"""
    now = datetime.now()
    end_time = now + time_left
    
    query = db.query(models.Event).filter(
        models.Event.shipping_deadline <= end_time,
        models.Event.shipping_deadline > now - timedelta(days=1)  # Don't check events older than 1 day
    )
    
    if min_time_left:
        start_time = now + min_time_left
        query = query.filter(models.Event.shipping_deadline >= start_time)
        
    if status:
        query = query.filter(models.Event.status == status)
        
    return (
        query
        .options(joinedload(models.Event.participants))
        .options(joinedload(models.Event.pairs).joinedload(models.SantaPair.receiver))
        .all()
    )


def create_feedback(
    db: Session,
    pair_id: int,
    message: str,
    rating: Optional[int] = None
) -> models.Feedback:
    """Create a new feedback entry"""
    # Validate rating if provided
    if rating is not None and (rating < 1 or rating > 5):
        raise ValueError("Rating must be between 1 and 5")
        
    db_feedback = models.Feedback(
        pair_id=pair_id,
        message=message,
        rating=rating
    )
    
    db.add(db_feedback)
    db.commit()
    db.refresh(db_feedback)
    return db_feedback


def get_feedback_for_pair(
    db: Session,
    pair_id: int
) -> List[models.Feedback]:
    """Get all feedback for a specific Santa-receiver pair"""
    return (
        db.query(models.Feedback)
        .filter(models.Feedback.pair_id == pair_id)
        .order_by(models.Feedback.created_at.desc())
        .all()
    )


def has_feedback(
    db: Session,
    pair_id: int
) -> bool:
    """Check if feedback has been left for this pair"""
    return (
        db.query(models.Feedback)
        .filter(models.Feedback.pair_id == pair_id)
        .first() is not None
    )


def get_average_rating(
    db: Session,
    santa_id: int
) -> Optional[float]:
    """Calculate average rating for a Santa"""
    result = (
        db.query(
            models.Feedback,
            models.SantaPair
        )
        .join(
            models.SantaPair,
            models.Feedback.pair_id == models.SantaPair.id
        )
        .filter(models.SantaPair.santa_id == santa_id)
        .filter(models.Feedback.rating.isnot(None))
        .with_entities(models.Feedback.rating)
        .all()
    )
    
    if not result:
        return None
        
    ratings = [r[0] for r in result if r[0] is not None]
    return sum(ratings) / len(ratings) if ratings else None
