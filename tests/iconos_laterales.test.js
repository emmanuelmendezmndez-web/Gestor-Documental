const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const leer = archivo => fs.readFileSync(path.join(__dirname, '..', archivo), 'utf8');
const plantilla = leer('app/templates/base.html');
const estilos = leer('app/static/styles-02-base-estructura.css');

function bloque(css, comienzo) {
    let nivel = 1, fin = comienzo + 1;
    while (nivel && fin < css.length) {
        if (css[fin] === '{') nivel++;
        if (css[fin] === '}') nivel--;
        fin++;
    }
    assert.equal(nivel, 0, 'el bloque CSS debe estar cerrado');
    return css.slice(comienzo + 1, fin - 1);
}

test('cada acceso conserva su etiqueta accesible y su icono decorativo', () => {
    for (const nombre of ['Inicio', 'Biblioteca', 'Expedientes', 'Subir documento', 'Usuarios', 'Papelera', 'Actividad', 'Cerrar sesión']) {
        const etiqueta = new RegExp('<(?:a|button)\\b[^>]*aria-label="' + nombre + '"[^>]*>([\\s\\S]*?)</(?:a|button)>');
        const acceso = plantilla.match(etiqueta);
        assert.ok(acceso, nombre);
        assert.match(acceso[1], /<svg\b[^>]*aria-hidden="true"/);
    }
});

test('las animaciones son puntuales y solo se activan sin movimiento reducido', () => {
    const indice = estilos.indexOf('@media (prefers-reduced-motion: no-preference)');
    assert.notEqual(indice, -1);
    const reglas = bloque(estilos, estilos.indexOf('{', indice));
    for (const clase of ['inicio', 'pagina', 'carpeta', 'subir', 'persona', 'persona-secundaria', 'tapa', 'actividad', 'salir']) {
        assert.match(reglas, new RegExp('\\.sidebar \\.nav-icono-' + clase + '\\s*\\{[^}]*animation:[^}]*(580|680)ms'));
    }
    assert.match(reglas, /:focus-visible/);
    assert.match(reglas, /@media\s*\(hover:\s*hover\)/);
    assert.doesNotMatch(reglas, /\binfinite\b/);
});

test('Biblioteca incluye una página móvil y subida combina nube y flecha', () => {
    const biblioteca = plantilla.match(/aria-label="Biblioteca"[^>]*>([\s\S]*?)<\/a>/);
    const subida = plantilla.match(/aria-label="Subir documento"[^>]*>([\s\S]*?)<\/a>/);
    assert.match(biblioteca[1], /nav-icono-pagina/);
    assert.match(estilos, /@keyframes siged-nav-pagina\s*\{[^}]*rotateY\(0deg\)/);
    assert.match(estilos, /rotateY\(180deg\)/);
    assert.match(subida[1], /<svg[\s\S]*?<path d="M7 17\.5H6a4/);
    assert.match(subida[1], /nav-icono-subir/);
});
