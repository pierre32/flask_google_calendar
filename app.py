import datetime
import os
import httplib2
import json

from dotenv import load_dotenv
from flask import Flask, render_template, session, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_security import Security, SQLAlchemyUserDatastore, UserMixin, RoleMixin, login_required
from flask_mail import Mail
from googleapiclient.discovery import build
from oauth2client import client
from sqlalchemy.exc import IntegrityError


SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
load_dotenv()
app = Flask(__name__)
app.config['DEBUG'] = os.getenv('DEBUG')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECURITY_PASSWORD_SALT'] = os.getenv('SECURITY_PASSWORD_SALT')
app.config['SECURITY_REGISTERABLE'] = True
app.config['SECURITY_CONFIRMABLE'] = True
app.config['SECURITY_EMAIL_SENDER'] = 'noreply@calendar'
app.config['MAIL_DEBUG'] = 0
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = os.getenv('MAIL_PORT')
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL')
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')


db = SQLAlchemy(app)
migrate = Migrate(app, db)
mail = Mail(app)


roles_users = db.Table('roles_users',
        db.Column('user_id', db.Integer(), db.ForeignKey('user.id')),
        db.Column('role_id', db.Integer(), db.ForeignKey('role.id')))


class Role(db.Model, RoleMixin):
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128))
    email = db.Column(db.String(255), unique=True)
    password = db.Column(db.String(255))
    active = db.Column(db.Boolean())
    confirmed_at = db.Column(db.DateTime())
    roles = db.relationship('Role', secondary=roles_users,
                            backref=db.backref('users', lazy='dynamic'))


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    start = db.Column(db.Date())
    created_at = db.Column(db.DateTime())
    __table_args__ = (
        db.UniqueConstraint('title', 'start'),
    )


user_datastore = SQLAlchemyUserDatastore(db, User, Role)
security = Security(app, user_datastore)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/oauth2callback')
def oauth2callback():
    flow = client.flow_from_clientsecrets(
        'client_secrets.json',
        scope='https://www.googleapis.com/auth/calendar',
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    if 'code' not in request.args:
        auth_uri = flow.step1_get_authorize_url()
        return redirect(auth_uri)
    else:
        auth_code = request.args.get('code')
        credentials = flow.step2_exchange(auth_code)
        session['credentials'] = credentials.to_json()
        return redirect(url_for('index'))


@app.route('/calendar')
@login_required
def calendar():
    if 'credentials' not in session:
        return redirect(url_for('oauth2callback'))
    credentials = client.OAuth2Credentials.from_json(session['credentials'])
    if credentials.access_token_expired:
        return redirect(url_for('oauth2callback'))
    return render_template('calendar.html')


@app.route('/data')
@login_required
def data():
    credentials = client.OAuth2Credentials.from_json(session['credentials'])
    http_auth = credentials.authorize(httplib2.Http())
    service = build('calendar', 'v3', http_auth)

    start = request.args['start']
    start = datetime.datetime.fromisoformat(start)
    old_threshold = datetime.datetime.now() - datetime.timedelta(minutes=1)
    events = Event.query.filter(Event.start > start, Event.created_at > old_threshold).all()

    if not events:
        start = start.isoformat()
        events_result = service.events().list(calendarId='primary', timeMin=start,
                                            maxResults=100, singleEvents=True,
                                            orderBy='startTime').execute()
        events = events_result.get('items', [])
        for event in events:
            event_start = event['start'].get('dateTime', event['start'].get('date'))
            event_start = datetime.datetime.fromisoformat(start).date()
            try:
                db.session.add(
                    Event(
                        title=event['summary'],
                        start=event_start,
                        created_at=datetime.datetime.now()
                    )
                )
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

    events = Event.query.filter(Event.start > start).all()
    events = [
        {
            'title': event.title,
            'start': event.start.isoformat()
        } for event in events
    ]
    return json.dumps(events)


if __name__ == '__main__':
    app.run()
