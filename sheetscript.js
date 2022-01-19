const INPUT = 1;
const OUTDRIVE = 1;
const OUTPUZ = 2;
const ANSWER = 6;
const SHEETID = 123456789;
const SERVER = 'http://example.com';

const internal = SpreadsheetApp.getActive().getSheets().filter(s => s.getSheetId() === SHEETID)[0];

function gc(range, col, sheet) {
  return (sheet || range.getSheet()).getRange(range.getRow(), col);
}

function gr(range, col) {
  for (let row = range.getRow(); row >= 1; --row) {
    let test = range.getSheet().getRange(row, col).getValue();
    if (test && test[0] === '#') return test;
  }
  // should never get here
}

function fetch(e, obj) {
  obj.name = gc(e.range, INPUT).getValue();
  obj.round = gr(e.range, INPUT);
  if (!obj.name) return '';
  const ret = JSON.parse(UrlFetchApp.fetch(SERVER+'/_hunthelper_', {
    method: 'post',
    payload: JSON.stringify(obj)
  }));
  if (ret.drive) gc(e.range, OUTDRIVE, internal).setValue(ret.drive);
  if (ret.puzzle) gc(e.range, OUTPUZ, internal).setValue(ret.puzzle);
  if (ret.note) e.range.setNote(ret.note);
}

function hi(e) {
  if (e.range.getSheet().getSheetId() !== 0) return;
  if (e.range.getColumn() === 1) {
    if (e.oldValue) {
      fetch(e, { action: 'rename', oldname: e.oldValue });
    } else {
      for (let i = 0; i < e.range.getHeight(); ++i) {
        fetch(e, { action: 'fetch' });
      }
    }
  } else if (e.range.getColumn() === 6) {
    if (e.value) {
      fetch(e, { action: 'solve', ans: e.value });
    }
  }
}
