const assert = require('node:assert/strict');
const test = require('node:test');
const {selectionInRectangle,shouldRefreshResults,pageInfo} = require('../static/review-controls.js');

const cards = [
  {id:'a',rect:{left:0,top:0,right:100,bottom:100}},
  {id:'b',rect:{left:120,top:0,right:220,bottom:100}},
  {id:'c',rect:{left:0,top:120,right:100,bottom:220}},
];

test('normal drag replaces prior selection with intersecting cards', () => {
  const selection=selectionInRectangle(cards,{left:10,top:10,right:150,bottom:90},new Set(['c']),false);
  assert.deepEqual([...selection],['a','b']);
});

test('Ctrl/Command drag adds cards while keeping prior selection', () => {
  const selection=selectionInRectangle(cards,{left:130,top:10,right:160,bottom:60},new Set(['c']),true);
  assert.deepEqual([...selection],['c','b']);
});

test('empty-space drag clears replace selection and preserves additive selection', () => {
  const rectangle={left:105,top:10,right:115,bottom:90};
  assert.equal(selectionInRectangle(cards,rectangle,new Set(['a']),false).size,0);
  assert.deepEqual([...selectionInRectangle(cards,rectangle,new Set(['a']),true)],['a']);
});

test('edge touching is not intersection; non-selectable cards are excluded by the caller', () => {
  assert.equal(selectionInRectangle([cards[0]],{left:100,top:0,right:120,bottom:100},new Set(),false).size,0);
});

test('scan result refresh waits for cadence and refreshes as soon as idle', () => {
  const options={pending:true,selectedCount:0,revealed:false,dragging:false,running:true,elapsed:3000};
  assert.equal(shouldRefreshResults(options),false);
  assert.equal(shouldRefreshResults({...options,elapsed:6000}),true);
  assert.equal(shouldRefreshResults({...options,running:false}),true);
  assert.equal(shouldRefreshResults({...options,pending:false,running:false}),false);
});

test('pending results never interrupt selection, revealed previews or dragging', () => {
  const options={pending:true,selectedCount:0,revealed:false,dragging:false,running:true,elapsed:9000};
  for(const field of ['selectedCount','revealed','dragging']) {
    assert.equal(shouldRefreshResults({...options,[field]:field==='selectedCount'?1:true}),false);
  }
});

test('page info clamps boundaries and handles empty and last partial pages', () => {
  assert.deepEqual(pageInfo(0,48,1),{page:1,pages:1,offset:0});
  assert.deepEqual(pageInfo(50,24,3),{page:3,pages:3,offset:48});
  assert.deepEqual(pageInfo(50,24,99),{page:3,pages:3,offset:48});
  assert.deepEqual(pageInfo(50,24,0),{page:1,pages:3,offset:0});
  assert.deepEqual(pageInfo(50,96,2),{page:1,pages:1,offset:0});
});
