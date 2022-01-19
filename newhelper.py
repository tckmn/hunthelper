#!/usr/bin/env python3

from datetime import datetime
import code
import http.server
import itertools
import json
import pickle
import requests
import threading
import time
import urllib

PATH = '/_hunthelper_'
CONFIG = lambda: type('config_object', (), json.load(open('config.json')))


normalize = lambda name: ''.join(ch if ch.isalpha() or ch.isdigit() else
                                 '-' if ch == ' ' else
                                 '' for ch in name.lower()) or name
metafy = lambda name: f'[META] {name[1:].strip()}' if name[0] == '#' else name
demetafy = lambda name: f'{name[1:].strip()}' if name[0] == '#' else name
fixify = lambda url, is_meta: url.replace('puzzle', 'round') if is_meta else url
fixify = lambda url, is_meta: url
ping = f'<@{CONFIG().discord_pingid}>'

class NormDict:
    def __init__(self):
        self.underlying = dict()

    def contains(self, k): return normalize(k) in self.underlying
    def get(self, k, k2):
        v = self.underlying.get(normalize(k), dict())
        return v[k2] if k2 in v else None
    def set(self, k, v):
        self.underlying[normalize(k)] = v
    def move(self, korig, knew):
        if normalize(korig) == normalize(knew): return
        self.underlying[normalize(knew)] = self.underlying[normalize(korig)]
        del self.underlying[normalize(korig)]

    def __getstate__(self): return self.__dict__
    def __setstate__(self, d): self.__dict__ = d

class HuntHelper:
    def __init__(self):
        self.puzzles = NormDict()
        self.drive_token = ''
        self.drive_expires = 0
        self.solvecount = 0

    def __getstate__(self): return self.__dict__
    def __setstate__(self, d): self.__dict__ = d

    def drivelink(self, name, override=None): return f'https://docs.google.com/spreadsheets/d/{override or self.puzzles.get(name, "drive")}/edit'
    def puzlink(self, name): return fixify(CONFIG().puzprefix, name[0] == '#') + normalize(demetafy(name))
    def links(self, name): return { 'drive': self.drivelink(name), 'puzzle': self.puzlink(name) }

    def handle(self, data):
        action = data['action']
        name = data.get('name')
        rnd = data.get('round')

        if action == 'fetch':
            if not self.puzzles.contains(name):
                self.discord_log(f'creating puzzle {name}')
                self.puzzles.set(name, self.make_puzzle(name, rnd))
            return {
                **self.links(name)
            }

        elif action == 'rename':
            oldname = data['oldname']
            if not self.puzzles.contains(oldname):
                self.discord_log(f'{ping} WARNING: renaming nonexistent {oldname} to {name}')
                self.puzzles.set(name, self.make_puzzle(name, rnd))
            else:
                self.discord_log(f'{ping} WARNING: renaming {oldname} to {name}')
                self.puzzles.move(oldname, name)
            return {
                **self.links(name),
                'note': f'{datetime.now()}: renamed from {oldname} to {name}'
            }

        elif action == 'solve':
            self.discord_log(f'Puzzle *{metafy(name)}* solved with answer **{data["ans"]}**! :tada:', CONFIG().discord_announce)
            self.mark_solved(name)
            return {}

        else:
            self.discord_log(f'{ping} unknown action??? {action}')
            return {
                'note': f'{datetime.now()}: something extremely confusing and bad happened'
            }

    def make_puzzle(self, name, rname):
        is_round = name[0] == '#'
        truename = metafy(name)

        if is_round:
            drive_parent = self.create_drive(name[1:].strip(), 'folder', CONFIG().drive_root)
            discord_parent = self.create_discord(name[1:].strip(), 4)
        else:
            drive_parent = self.puzzles.get(rname, '^drive')
            discord_parent = self.puzzles.get(rname, '^discord')

        drive = self.create_drive(truename, 'spreadsheet', drive_parent)
        discord = self.create_discord(truename.replace('[META] ', 'ᴹᴱᵀᴬ-'), 0, parent_id=discord_parent, topic=f'{self.puzlink(name)} | {self.drivelink(None, drive)}')

        return {
            'drive': drive,
            'discord': discord,
            **({
                '^drive': drive_parent,
                '^discord': discord_parent
            } if is_round else {})
        }

    def mark_solved(self, name):
        requests.patch(f'https://discord.com/api/v8/channels/{self.puzzles.get(name, "discord")}', json={
            'parent_id': CONFIG().discord_solved[self.solvecount // 50]
        }, headers={
            'Authorization': f'Bot {CONFIG().discord_bot}'
        })
        self.solvecount += 1

        self.drive_check_token()
        requests.patch(f'https://www.googleapis.com/drive/v3/files/{self.puzzles.get(name, "drive")}', json={
            'name': f'[SOLVED] {metafy(name)}'
        }, headers={
            'Authorization': f'Bearer {self.drive_token}'
        })

    def create_drive(self, name, mime, parent):
        self.drive_check_token()
        resp = requests.post('https://www.googleapis.com/drive/v3/files', json={
            'name': name,
            'mimeType': 'application/vnd.google-apps.' + mime,
            'parents': [parent]
        }, headers={
            'Authorization': f'Bearer {self.drive_token}'
        })
        print(resp)
        print(resp.text)
        self.discord_log(f'created drive {mime}: {name} ({resp.status_code})')
        try:
            return json.loads(resp.text)['id']
        except:
            self.discord_log(f'failed! <@{CONFIG().discord_pingid}>')
            return 'FAILED'

    def drive_check_token(self):
        if self.drive_expires < time.time() + 10:
            resp = requests.post('https://oauth2.googleapis.com/token', {
                'client_id': CONFIG().drive_client_id,
                'client_secret': CONFIG().drive_client_secret,
                'refresh_token': CONFIG().drive_refresh_token,
                'grant_type': 'refresh_token'
            })
            print(resp)
            print(resp.text)
            resp = json.loads(resp.text)
            self.drive_token = resp['access_token']
            self.drive_expires = time.time() + resp['expires_in']

    def create_discord(self, name, chtype, **extra):
        resp = requests.post(f'https://discord.com/api/v8/guilds/{CONFIG().discord_guild}/channels', json={
            'name': name,
            'type': chtype,
            **extra
        }, headers={
            'Authorization': f'Bot {CONFIG().discord_bot}'
        })
        print(resp)
        print(resp.text)
        self.discord_log(f'created discord channel{" group" if chtype == 4 else ""}: {name} ({resp.status_code})')
        try:
            return json.loads(resp.text)['id']
        except:
            self.discord_log(f'failed! <@{CONFIG().discord_pingid}>')
            return 'FAILED'

    def discord_log(self, text, chan=None):
        print(f'(log {chan}) {text}')
        resp = requests.post(f'https://discord.com/api/v8/channels/{chan or CONFIG().discord_log}/messages', json={
            'content': text
        }, headers={
            'Authorization': f'Bot {CONFIG().discord_bot}'
        })
        if resp.status_code // 100 != 2:
            print(resp)
            print(resp.text)


try:    helper = pickle.load(open('helperdata', 'rb'))
except: helper = HuntHelper()

class HuntHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        print(self.path)
        if self.path != PATH: return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(json.dumps(helper.handle(json.loads(body))).encode())
        pickle.dump(helper, open('helperdata', 'wb'))

# helper.drive_check_token()
# __import__('sys').exit()

server = http.server.HTTPServer(('', CONFIG().port), HuntHandler)
threading.Thread(target=server.serve_forever).start()
helper.discord_log('bot started')
code.interact(local=locals())
helper.discord_log('bot stopped manually')
server.shutdown()
