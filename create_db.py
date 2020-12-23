from app import db, user_datastore


db.drop_all()
db.create_all()
user_datastore.create_user(email='matt@nobien.net', password='password')
db.session.commit()
