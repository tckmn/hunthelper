#!/usr/bin/env python3

import http.server
import json
import pickle
import requests
import time
import urllib

PORT = 1337
SEP = '~.'
CONFIG = json.load(open('config.json'))


class HuntHelper:
    def __init__(self):
        self.cells = []
        self.rounds = dict()
        self.puzzles = dict()
        self.token = ''
        self.expires = 0

    # make pickle behave as desired
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

        # puzzle
        if self.curround:
            if cell not in self.puzzles[self.curround]:
                self.puzzles[self.curround][cell] = self.make_sheet(self.curround, cell)
            return f'https://docs.google.com/spreadsheets/d/{self.puzzles[self.curround][cell]}/edit'

        # round
        self.curround = cell
        if cell not in self.rounds:
            self.rounds[cell] = self.make_folder(cell)
            self.puzzles[cell] = dict()
        return f'meta for {cell}'

    def make_sheet(self, rnd, cell):
        return self.create(cell, 'application/vnd.google-apps.spreadsheet', self.rounds[rnd])

    def make_folder(self, rnd):
        return self.create(rnd, 'application/vnd.google-apps.folder', CONFIG['root'])

    def create(self, name, mime, parent):
        self.check_token()
        resp = requests.post('https://www.googleapis.com/drive/v3/files', json={
            'name': name,
            'mimeType': mime,
            'parents': [parent]
        }, headers={
            'Authorization': f'Bearer {self.token}'
        })
        print(resp)
        print(resp.text)
        return json.loads(resp.text)['id']

    def check_token(self):
        if self.expires < time.time() + 10:
            resp = requests.post('https://oauth2.googleapis.com/token', {
                'client_id': CONFIG['client_id'],
                'client_secret': CONFIG['client_secret'],
                'refresh_token': CONFIG['refresh_token'],
                'grant_type': 'refresh_token'
            })
            print(resp)
            print(resp.text)
            resp = json.loads(resp.text)
            self.token = resp['access_token']
            self.expires = time.time() + resp['expires_in']


try:    helper = pickle.load(open('helperdata', 'rb'))
except: helper = HuntHelper()

class HuntHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cells = urllib.parse.unquote(self.path[1:]).rstrip(SEP).split(SEP)
        updated = helper.update(cells)

        self.send_response(200)
        self.send_header('Content-type', 'text/csv')
        self.end_headers()
        self.wfile.write(updated.encode())

http.server.HTTPServer(('', PORT), HuntHandler).serve_forever()
