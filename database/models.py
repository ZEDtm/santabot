from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session
import datetime
from typing import Optional, List
import os

from config import settings

# Create SQLAlchemy engine and session
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all models
Base = declarative_base()

class Event(Base):
    __tablename__ = 'events'
    
    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, nullable=False, index=True)  # Telegram user ID of the admin who created the event
    group_id = Column(Integer, nullable=False)
    group_chat_id = Column(Integer, nullable=True)  # Telegram group chat ID
    group_name = Column(String(255), nullable=True)  # Name of the group chat
    title = Column(String(100), nullable=False)
    photo_id = Column(String(255), nullable=True)
    registration_end = Column(DateTime, nullable=False)
    shipping_deadline = Column(DateTime, nullable=False)
    budget = Column(Integer, nullable=True)
    status = Column(String(20), default='registration')
    created_at = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))  # When the event was created
    
    participants = relationship("Participant", back_populates="event")
    pairs = relationship("SantaPair", back_populates="event")

class Participant(Base):
    __tablename__ = 'participants'
    
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    telegram_id = Column(Integer, nullable=False)
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    wishes = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    delivery_methods = Column(Text, nullable=True)
    
    event = relationship("Event", back_populates="participants")
    santa_pairs = relationship("SantaPair", foreign_keys="[SantaPair.santa_id]", back_populates="santa")
    receiver_pairs = relationship("SantaPair", foreign_keys="[SantaPair.receiver_id]", back_populates="receiver")

class SantaPair(Base):
    __tablename__ = 'santa_pairs'
    
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    santa_id = Column(Integer, ForeignKey('participants.id'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('participants.id'), nullable=False)
    
    event = relationship("Event", back_populates="pairs")
    santa = relationship("Participant", foreign_keys=[santa_id], back_populates="santa_pairs")
    receiver = relationship("Participant", foreign_keys=[receiver_id], back_populates="receiver_pairs")
    messages = relationship("AnonymousMessage", back_populates="pair")
    gift_confirmations = relationship("GiftConfirmation", back_populates="pair")
    feedback = relationship("Feedback", back_populates="pair")

class AnonymousMessage(Base):
    __tablename__ = 'anonymous_messages'
    
    id = Column(Integer, primary_key=True, index=True)
    pair_id = Column(Integer, ForeignKey('santa_pairs.id'), nullable=False)
    from_santa = Column(Boolean, nullable=False, default=True)
    message_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    
    pair = relationship("SantaPair", back_populates="messages")

class GiftConfirmation(Base):
    __tablename__ = 'gift_confirmations'
    
    id = Column(Integer, primary_key=True, index=True)
    pair_id = Column(Integer, ForeignKey('santa_pairs.id'), nullable=False)
    sent_at = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    tracking_number = Column(String(100), nullable=True)
    message = Column(Text, nullable=True)
    
    pair = relationship("SantaPair", back_populates="gift_confirmations")


class Feedback(Base):
    __tablename__ = 'feedback'
    
    id = Column(Integer, primary_key=True, index=True)
    pair_id = Column(Integer, ForeignKey('santa_pairs.id'), nullable=False)
    message = Column(Text, nullable=False)
    rating = Column(Integer, nullable=True)  # Optional rating from 1 to 5
    created_at = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    
    pair = relationship("SantaPair", back_populates="feedback")

def init_db():
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Create a test admin if none exists
    db = SessionLocal()
    try:
        # Check if we need to create any initial data
        pass
    finally:
        db.close()

init_db()
