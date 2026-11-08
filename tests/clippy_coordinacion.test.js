const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function iniciar(ruta = '/inicio', config = {}) {
    let reloj = 10000, secuencia = 0;
    const timers = new Map(), eventos = {}, dichos = [];
    const figura = {style:{}, classList:{add(){}, remove(){}, contains(){return false;}}, matches:()=>false, setAttribute(){}, addEventListener(tipo, fn){ this[tipo] = fn; }};
    const busqueda = {open:false}, confirmacion = {open:false};
    class Entrada { constructor(){ this.type='text'; this.value='ficticio'; this.dataset={clippyRead:'Búsqueda'}; } hasAttribute(){return true;} closest(){return null;} }
    const document = {readyState:'complete', addEventListener(tipo, fn){ (eventos[tipo] ||= []).push(fn); },
        getElementById(id){return id === 'busqueda-asistida' ? busqueda : id === 'dialogo-confirmacion' ? confirmacion : null;},
        querySelector(q){return q === '.clippy' ? figura : null;}, querySelectorAll(){return [];}};
    const agente = {_getIdleAnimation(){}, hasAnimation(){return false;}, _onQueueEmpty(){}, _queue:{}, _balloon:{hide(){}, _balloon:{hide(){}}},
        speak(texto){dichos.push(texto);}, stop(){}, moveTo(){}, show(){}};
    const window = {clippy:true, sigedClippyConfig:{basePath:'', usuarioId:1, nombre:'Prueba', ...config}, location:{pathname:ruta, search:''},
        innerHeight:800, innerWidth:1200, matchMedia:()=>({matches:true}), requestAnimationFrame(){}, addEventListener(){}, removeEventListener(){},
        setTimeout(fn, ms){const id=++secuencia; timers.set(id,{fn, ms}); return id;}, clearTimeout(id){timers.delete(id);}};
    class Fecha extends Date { static now(){return reloj;} }
    const ctx = {window, document, clippy:{load(_nombre, fn){fn(agente);}}, Date:Fecha, URLSearchParams, HTMLElement:Entrada, HTMLInputElement:Entrada, getComputedStyle:()=>({display:'none'}), console};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/clippy_asistente.js'), 'utf8'), ctx);
    return {busqueda, confirmacion, figura, dichos, eventos, Entrada, timers, avanzar(ms){reloj += ms;}, ejecutar(ms){const lista=[...timers.entries()].filter(([, t])=>t.ms===ms); for (const [id,t] of lista) {timers.delete(id); t.fn();}}};
}
test('el diálogo asistido y la confirmación bloquean lectura y consejos automáticos', () => {
    const p = iniciar(); const campo = new p.Entrada();
    for (const fn of p.eventos.input) fn({target:campo});
    p.busqueda.open = true; p.avanzar(3000); p.ejecutar(3000);
    assert.deepEqual(p.dichos, []);
    p.busqueda.open = false; p.confirmacion.open = true;
    for (const fn of p.eventos.input) fn({target:campo});
    p.avanzar(3000); p.ejecutar(3000); assert.deepEqual(p.dichos, []);
});
test('la lectura espera a que termine la escritura y se mantiene la ayuda solicitada', () => {
    const p = iniciar('/expedientes', {puedeGestionarExpedientes:false});
    const campo = new p.Entrada();
    for (const fn of p.eventos.input) fn({target:campo});
    p.avanzar(3000); p.ejecutar(3000); assert.deepEqual(p.dichos, ['Búsqueda: ficticio']);
    p.figura.click(); assert.match(p.dichos.at(-1), /consultar/); assert.doesNotMatch(p.dichos.at(-1), /crear|vincular/i);
});
