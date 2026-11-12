const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const leer = archivo => fs.readFileSync(path.join(__dirname, "..", archivo), "utf8");
const plantilla = leer("app/templates/base.html");
const iconos = leer("app/templates/_iconos_phosphor.html");
const estilos = leer("app/static/styles-02-base-estructura.css");

test("la navegación conserva sus etiquetas y asigna los SVG decorativos de Phosphor", () => {
    for (const [nombre, icono] of [
        ["Inicio", "house-line"], ["Biblioteca", "books"], ["Expedientes", "folder-open"],
        ["Mensajería", "wechat-logo"], ["Subir documento", "cloud-arrow-up"], ["Usuarios", "users"],
        ["Papelera", "trash"], ["Actividad", "clock-user"],
    ]) {
        const acceso = plantilla.match(new RegExp('<a[^>]*aria-label="' + nombre + '"[^>]*>([\\s\\S]*?)</a>'));
        assert.ok(acceso, nombre);
        assert.match(acceso[0], /data-animar-icono/);
        assert.ok(acceso[1].includes('icono_animado("' + icono + '")'), icono);
    }
    assert.match(iconos, /<svg\b[^>]*aria-hidden="true"/);
    assert.match(plantilla, /<button[^>]*aria-label="Cerrar sesi.n"[^>]*data-animar-icono[^>]*>\s*{{ icono_animado\("sign-out"\) }}/);
    assert.match(plantilla, /<button[^>]*id="sidebar-toggle"[^>]*aria-expanded="false"[^>]*data-animar-icono[^>]*>\s*{{ icono_animado\("square-half"\) }}/);
    assert.match(estilos, /\.sidebar-toggle\[aria-expanded="true"\] \.icono-orientacion-barra\s*\{\s*transform: scaleX\(-1\)/);
    assert.match(plantilla, /<button[^>]*class="buscar-accion"[^>]*>\s*<i class="ph-bold ph-magnifying-glass"/);
});

test("los movimientos internos se asignan a piezas de SVG independientes", () => {
    for (const pieza of [
        "libro-recto", "libro-inclinado", "carpeta-frente", "globo-delante", "globo-detras",
        "flecha-subir", "usuario-primero", "usuario-segundo", "tapa", "manecillas", "campana", "flecha-salir",
    ]) {
        assert.ok(iconos.includes('<path class="icono-' + pieza + '"'), pieza);
        assert.match(estilos, new RegExp("\\.icono-" + pieza + " [^{]*\\{[^}]*--movimiento-icono:"));
    }
    assert.match(estilos, /@media \(prefers-reduced-motion: no-preference\)/);
    assert.doesNotMatch(estilos, /animation:[^;]*\binfinite\b/);
});

test("cursor, foco, toque y notificaciones activan una reacción puntual y respetan movimiento reducido", () => {
    const eventos = new Map();
    const clases = new Set();
    const movimiento = { matches: false };
    const temporizadores = [];
    const control = {
        closest: () => control,
        contains: elemento => elemento === control,
        matches: selector => selector === ":focus-visible",
        classList: {
            add: clase => clases.add(clase),
            remove: clase => clases.delete(clase),
            contains: clase => clases.has(clase),
        },
    };
    vm.runInNewContext(leer("app/static/navegacion.js"), {
        document: { getElementById: () => null, addEventListener: (nombre, fn) => eventos.set(nombre, fn) },
        window: { matchMedia: () => movimiento, setTimeout: (fn, ms) => temporizadores.push({ fn, ms }) },
    });
    const disparar = (nombre, extra) => eventos.get(nombre)({ target: control, ...extra });
    const terminar = () => {
        assert.equal(temporizadores.length, 1);
        const { fn, ms } = temporizadores.pop();
        assert.ok(ms >= 250 && ms <= 400);
        fn();
        assert.equal(clases.size, 0);
    };
    disparar("pointerover", { pointerType: "mouse", relatedTarget: null });
    disparar("click");
    terminar();
    disparar("pointerover", { pointerType: "mouse", relatedTarget: control });
    disparar("pointerover", { pointerType: "touch" });
    assert.equal(temporizadores.length, 0);
    disparar("pointerdown", { pointerType: "touch" });
    terminar();
    disparar("focusin");
    terminar();
    disparar("animar-icono");
    terminar();
    movimiento.matches = true;
    disparar("focusin");
    disparar("animar-icono");
    assert.equal(temporizadores.length, 0);
});
