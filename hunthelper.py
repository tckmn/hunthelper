#!/usr/bin/env python3

import http.server
import json
import pickle
import requests
import time
import urllib

PORT = 1337
SEP = '~.'
PREFIX = '/_hunthelper_'
CONFIG = type('config_object', (), json.load(open('config.json')))


make_link = lambda sheet_id: f'https://docs.google.com/spreadsheets/d/{sheet_id}/edit'


class Round:
    def __init__(self, folder, channel):
        self.folder = folder
        self.channel = channel
        self.puzzles = dict()

    def __getstate__(self): return self.__dict__
    def __setstate__(self, d): self.__dict__ = d

class Puzzle:
    def __init__(self, sheet, channel):
        self.sheet = sheet
        self.channel = channel

    def __getstate__(self): return self.__dict__
    def __setstate__(self, d): self.__dict__ = d

class HuntHelper:
    def __init__(self):
        self.cells = []
        self.rounds = dict()
        self.drive_token = ''
        self.drive_expires = 0

    def __getstate__(self): return self.__dict__
    def __setstate__(self, d): self.__dict__ = d

    def update(self, cells):
        # TODO check for renames and accidents
        self.cells = cells
        self.curround = None
        res = '\n'.join(map(self.render, self.cells))
        del self.curround
        pickle.dump(self, open('helperdata', 'wb'))
        return res

    def render(self, cell):
        if not cell:
            self.curround = None
            return ''

        # rendering puzzle
        if self.curround:
            if self.curround not in self.rounds:
                self.rounds[self.curround] = self.make_round(self.curround)
            if cell not in self.rounds[self.curround].puzzles:
                self.rounds[self.curround].puzzles[cell] = self.make_puzzle(self.curround, cell)
            return make_link(self.rounds[self.curround].puzzles[cell].sheet)

        # rendering round
        self.curround = cell
        return f'meta for {cell}'

    def make_puzzle(self, rnd, cell):
        sheet = self.create_drive(cell, 'spreadsheet', self.rounds[rnd].folder)
        return Puzzle(sheet, self.create_discord(cell, 0, parent_id=self.rounds[rnd].channel, topic=make_link(sheet)))

    def make_round(self, rnd):
        return Round(self.create_drive(rnd, 'folder', CONFIG.drive_root),
                     self.create_discord(rnd, 4))

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
        return json.loads(resp.text)['id']

    def create_discord(self, name, chtype, **extra):
        resp = requests.post(f'https://discord.com/api/v8/guilds/{CONFIG.discord_guild}/channels', json={
            'name': name,
            'type': chtype,
            **extra
        }, headers={
            'Authorization': f'Bot {CONFIG.discord_bot}'
        })
        print(resp)
        print(resp.text)
        self.discord_log(f'created discord channel{" group" if chtype == 4 else ""}: {name} ({resp.status_code})')
        return json.loads(resp.text)['id']

    def drive_check_token(self):
        if self.drive_expires < time.time() + 10:
            resp = requests.post('https://oauth2.googleapis.com/token', {
                'client_id': CONFIG.drive_client_id,
                'client_secret': CONFIG.drive_client_secret,
                'refresh_token': CONFIG.drive_refresh_token,
                'grant_type': 'refresh_token'
            })
            print(resp)
            print(resp.text)
            resp = json.loads(resp.text)
            self.drive_token = resp['access_token']
            self.drive_expires = time.time() + resp['expires_in']

    def discord_log(self, text):
        requests.post(f'https://discord.com/api/v8/channels/{CONFIG.discord_log}/messages', json={
            'content': text
        }, headers={
            'Authorization': f'Bot {CONFIG.discord_bot}'
        })


try:    helper = pickle.load(open('helperdata', 'rb'))
except: helper = HuntHelper()

class HuntHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith(PREFIX):
            cells = urllib.parse.unquote(self.path[len(PREFIX):]).rstrip(SEP).split(SEP)
            updated = helper.update(cells)
        else:
            updated = 'bad'

        self.send_response(200)
        self.send_header('Content-type', 'text/csv')
        self.end_headers()
        self.wfile.write(updated.encode())

http.server.HTTPServer(('', PORT), HuntHandler).serve_forever()
