#!/usr/bin/env python3

import code
import http.server
import itertools
import json
import pickle
import requests
import threading
import time
import urllib

BIGSEP = '.~~.'
SEP = '~.'
PREFIX = '/_hunthelper_'
CONFIG = type('config_object', (), json.load(open('config.json')))


normalize = lambda name: ''.join(ch if ch.isalpha() or ch.isdigit() else
                                 '-' if ch == ' ' else
                                 '' for ch in name.lower())
drivelink = lambda sheet: f'https://docs.google.com/spreadsheets/d/{sheet}/edit'
puzlink = lambda name, typ: CONFIG.puzprefix+normalize(name) if typ is Puzzle else ''
linkify1 = lambda cur: f'{drivelink(cur.sheet)},{puzlink(cur.name, type(cur))}'
linkify2 = lambda name, typ, sheet: f'{puzlink(name, typ)} | {drivelink(sheet)}'.lstrip(' | ')

def rename(x, y, k, v):
    if k == x:
        v.name = y
        return (y, v)
    return (k, v)


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

            # make sure we don't rename rounds to puzzles or vice versa
            if x and y and ((x[0] == '#') != (y[0] == '#')):
                self.discord_log(f'<@{CONFIG.discord_pingid}> WARNING: bad rename, yelling at user')
                return 'BAD,please undo\n' * 300

            # if a puzzle gets renamed, don't change the link
            if x and y:
                self.discord_log(f'<@{CONFIG.discord_pingid}> WARNING: renaming {x} to {y}')
                if x[0] == '#':
                    self.rounds = dict(rename(x,y,k,v) for k,v in self.rounds.items())
                else:
                    for rnd in self.rounds.values():
                        rnd.puzzles = dict(rename(x,y,k,v) for k,v in rnd.puzzles.items())

        # render cells
        self.cells = cells
        self.curround = None
        res = '\n'.join(map(self.render, itertools.zip_longest(cells, solved)))
        del self.curround

        pickle.dump(self, open('helperdata', 'wb'))
        return res

    def render(self, x):
        cell, solved = x

        if not cell or all(not ch.isalpha() for ch in cell): return ''

        # check solvedness
        try:    cur = self.rounds[self.curround].puzzles[cell] if cell[0] != '#' else self.rounds[cell]
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
            self.discord_log(f'Puzzle *{cur.name}* solved! :tada:', CONFIG.discord_announce)

        # check the other way
        if cur and cur.solved and not solved:
            print(x)
            # self.discord_log(f'<@{CONFIG.discord_pingid}> puzzle unsolved???')

        # rendering puzzle
        if cell[0] != '#':
            if self.curround not in self.rounds:
                self.rounds[self.curround] = self.make_round(self.curround)
            if cell not in self.rounds[self.curround].puzzles:
                self.rounds[self.curround].puzzles[cell] = self.make_puzzle(self.curround, cell)
            return linkify1(self.rounds[self.curround].puzzles[cell])

        # rendering round
        cell = cell[1:].lstrip()
        self.curround = cell
        return linkify1(self.rounds[cell]) if cell in self.rounds else ''

    def make_puzzle(self, rnd, cell):
        sheet   = self.create_drive(cell, 'spreadsheet', self.rounds[rnd].folder)
        channel = self.create_discord(cell, 0, parent_id=self.rounds[rnd].group, topic=linkify2(cell, Puzzle, sheet))
        return Puzzle(cell, sheet, channel)

    def make_round(self, rnd):
        folder  = self.create_drive(rnd, 'folder', CONFIG.drive_root)
        sheet   = self.create_drive(f'[META] {rnd}', 'spreadsheet', folder)
        group   = self.create_discord(rnd, 4)
        channel = self.create_discord(f'ᴹᴱᵀᴬ-{rnd}', 0, parent_id=group, topic=linkify2('', Round, sheet))
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

    def discord_log(self, text, chan=None):
        print(f'(log {chan}) {text}')
        requests.post(f'https://discord.com/api/v8/channels/{chan or CONFIG.discord_log}/messages', json={
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
            for mapping in reversed(open('mapping').read().split('\n')[:-1]):
                x, y = mapping.split('\t')
                cells = cells.replace(y, x)
            print(cells)
            updated = helper.update(cells.split(SEP), solved.split(SEP))
        else:
            updated = 'bad'

        self.send_response(200)
        self.send_header('Content-type', 'text/csv')
        self.end_headers()
        self.wfile.write(updated.encode())

server = http.server.HTTPServer(('', CONFIG.port), HuntHandler)
threading.Thread(target=server.serve_forever).start()
helper.discord_log('bot started')
code.interact(local=locals())
helper.discord_log('bot stopped manually')
server.shutdown()
