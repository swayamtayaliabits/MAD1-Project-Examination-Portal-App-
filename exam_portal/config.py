import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = "change-this-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "instance", "emp.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    #The admin i made so that it is created automatically
    ADMIN_NAME = "System Admin"
    ADMIN_EMAIL = "admin@emp.local"
    ADMIN_PASSWORD = "Admin@123"
