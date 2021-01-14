#!/usr/bin/env python3

import http.server
import itertools
import json
import pickle
import requests
import time
import urllib

PORT = 1337
BIGSEP = '.~~.'
SEP = '~.'
PREFIX = '/_hunthelper_'
CONFIG = type('config_object', (), json.load(open('config.json')))


linkify = lambda sheet_id: f'https://docs.google.com/spreadsheets/d/{sheet_id}/edit'


class Round:
    def __init__(self, name, folder, sheet, group, channel):
        self.solved  = False
        self.name    = name
        self.folder  = folder
        self.sheet   = sheet
        self.group   = group
        self.channel = channel
        self.puzzles = dict()

    def __getstate__(self): return self.__dict__
    def __setstate__(self, d): self.__dict__ = d

class Puzzle:
    def __init__(self, name, sheet, channel):
        self.solved  = False
        self.name    = name
        self.sheet   = sheet
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

    def update(self, cells, solved):
        # check if a single cell was modified
        if len(self.cells) == len(cells) and sum(x!=y for x,y in zip(self.cells, cells)) == 1:
            i, x, y = next((i, x, y) for (i, (x, y)) in enumerate(zip(self.cells, cells)) if x != y)

            # make sure the cell directly above a round remains blank
            if not x and y and i+1 < len(cells) and cells[i+1]:
                self.discord_log(f'<@{CONFIG.discord_pingid}> WARNING: accidental round shift, yelling at user')
                return '\n'.join(['"BAD, please press undo"'] * 300)

            # if a puzzle gets renamed, don't change the link
            if x and y:
                self.discord_log(f'<@{CONFIG.discord_pingid}> WARNING: renaming {x} to {y}')
                if i == 0 or not cells[i-1]:
                    self.rounds = {(y if k==x else k): v for k,v in self.rounds.items()}
                else:
                    for rnd in self.rounds.values():
                        rnd.puzzles = {(y if k==x else k): v for k,v in rnd.puzzles.items()}

        # render cells
        self.cells = cells
        self.curround = None
        res = '\n'.join(map(self.render, itertools.zip_longest(cells, solved)))
        del self.curround

        pickle.dump(self, open('helperdata', 'wb'))
        return res

    def render(self, x):
        cell, solved = x

        if not cell:
            self.curround = None
            return ''

        # check solvedness
        try:    cur = self.rounds[self.curround].puzzles[cell] if self.curround else self.rounds[cell]
        except: cur = None
        if cur and not cur.solved and solved:
            self.drive_check_token()
            requests.patch(f'https://discord.com/api/v8/channels/{cur.channel}', json={
                'parent_id': CONFIG.discord_solved
            }, headers={
                'Authorization': f'Bot {CONFIG.discord_bot}'
            })
            requests.patch(f'https://www.googleapis.com/drive/v3/files/{cur.sheet}', json={
                'name': f'[SOLVED] {cur.name}'
            }, headers={
                'Authorization': f'Bearer {self.drive_token}'
            })
            cur.solved = True
            self.discord_log(f'marked as solved: {cur.name} with answer {solved}')

        # check the other way
        if cur and cur.solved and not solved:
            print(x)
            self.discord_log(f'<@{CONFIG.discord_pingid}> puzzle unsolved???')

        # rendering puzzle
        if self.curround:
            if self.curround not in self.rounds:
                self.rounds[self.curround] = self.make_round(self.curround)
            if cell not in self.rounds[self.curround].puzzles:
                self.rounds[self.curround].puzzles[cell] = self.make_puzzle(self.curround, cell)
            return linkify(self.rounds[self.curround].puzzles[cell].sheet)

        # rendering round
        self.curround = cell
        return linkify(self.rounds[cell].sheet) if cell in self.rounds else ''

    def make_puzzle(self, rnd, cell):
        sheet   = self.create_drive(cell, 'spreadsheet', self.rounds[rnd].folder)
        channel = self.create_discord(cell, 0, parent_id=self.rounds[rnd].group, topic=linkify(sheet))
        return Puzzle(cell, sheet, channel)

    def make_round(self, rnd):
        folder  = self.create_drive(rnd, 'folder', CONFIG.drive_root)
        sheet   = self.create_drive(f'[META] {rnd}', 'spreadsheet', folder)
        group   = self.create_discord(rnd, 4)
        channel = self.create_discord(f'ᴹᴱᵀᴬ-{rnd}', 0, parent_id = group, topic = linkify(sheet))
        return Round(f'[META] {rnd}', folder, sheet, group, channel)

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
            self.discord_log(f'failed! <@{CONFIG.discord_pingid}>')
            return 'FAILED'

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
        try:
            return json.loads(resp.text)['id']
        except:
            self.discord_log(f'failed! <@{CONFIG.discord_pingid}>')
            return 'FAILED'

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
        print(self.path)
        if self.path.startswith(PREFIX):
            cells, solved = urllib.parse.unquote(self.path[len(PREFIX):]).split(BIGSEP)
            updated = helper.update(cells.split(SEP), solved.split(SEP))
        else:
            updated = 'bad'

        self.send_response(200)
        self.send_header('Content-type', 'text/csv')
        self.end_headers()
        self.wfile.write(updated.encode())

http.server.HTTPServer(('', PORT), HuntHandler).serve_forever()
