const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function iniciar(movil = false) {
    const clases = new Set(['is-collapsed']), eventos = {}, eventosDocumento = {}, eventosBoton = {};
    const sidebar = {
        classList: {
            contains: nombre => clases.has(nombre),
            add: nombre => clases.add(nombre),
            remove: nombre => clases.delete(nombre),
            toggle: (nombre, valor) => valor ? clases.add(nombre) : clases.delete(nombre),
        },
        addEventListener: (nombre, fn) => { eventos[nombre] = fn; },
        contains: elemento => elemento?.enSidebar === true,
    };
    const boton = {enSidebar:true, atributos:{}, setAttribute(nombre, valor){this.atributos[nombre] = valor;}, addEventListener(nombre, fn){eventosBoton[nombre] = fn;}};
    const enlace = {enSidebar:true};
    const document = {
        activeElement: null,
        getElementById: id => id === 'sidebar-principal' ? sidebar : id === 'sidebar-toggle' ? boton : null,
        addEventListener(nombre, fn) { (eventosDocumento[nombre] ||= []).push(fn); },
    };
    const media = {matches:movil, addEventListener(){}};
    const window = {matchMedia:()=>media, clearTimeout(){}, setTimeout(){return 1;}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/navegacion.js'), 'utf8'), {window, document});
    return {sidebar, boton, enlace, eventos, eventosDocumento, eventosBoton};
}

test('el foco de un clic no expande ni intercepta el enlace compacto', () => {
    const p = iniciar();
    p.eventos.pointerdown({target:p.enlace});
    p.eventos.focusin({target:p.enlace});
    assert.equal(p.sidebar.classList.contains('is-collapsed'), true);
    p.eventosDocumento.pointerup[0]({target:p.enlace});
    p.eventos.click({target:p.enlace});
    assert.equal(p.sidebar.classList.contains('is-collapsed'), true);
});

test('la flecha alterna la barra con un solo clic', () => {
    const p = iniciar();
    assert.equal(p.boton.atributos['aria-expanded'], 'false');
    assert.equal(p.boton.atributos['aria-label'], 'Expandir barra lateral');
    p.eventos.pointerdown({target:p.boton}); p.eventos.focusin({target:p.boton});
    p.eventosDocumento.pointerup[0]({target:p.boton}); p.eventosBoton.click();
    assert.equal(p.sidebar.classList.contains('is-collapsed'), false);
    assert.equal(p.boton.atributos['aria-expanded'], 'true');
    assert.equal(p.boton.atributos['aria-label'], 'Contraer barra lateral');
    p.eventosBoton.click(); assert.equal(p.sidebar.classList.contains('is-collapsed'), true);
    assert.equal(p.boton.atributos['aria-label'], 'Expandir barra lateral');
});

test('el teclado conserva la expansión de enlaces y permite accionar la flecha', () => {
    const p = iniciar();
    p.eventos.focusin({target:p.boton});
    assert.equal(p.sidebar.classList.contains('is-collapsed'), true);
    p.eventosBoton.click(); assert.equal(p.sidebar.classList.contains('is-collapsed'), false);
    p.eventosBoton.click(); p.eventos.focusin({target:p.enlace});
    assert.equal(p.sidebar.classList.contains('is-collapsed'), false);
});

test('cancelar el puntero no bloquea el foco posterior y móvil permanece expandido', () => {
    const p = iniciar();
    p.eventos.pointerdown({target:p.enlace}); p.eventosDocumento.pointercancel[0]();
    p.eventos.focusin({target:p.enlace});
    assert.equal(p.sidebar.classList.contains('is-collapsed'), false);
    const movil = iniciar(true);
    assert.equal(movil.sidebar.classList.contains('is-collapsed'), false);
});
