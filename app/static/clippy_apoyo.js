(() => {
    const mensajes = {
        negacion: "Hay una negación o una exclusión. Revisa los criterios o reformula la búsqueda antes de continuar.",
        solo_lectura: "El apoyo de Clippy admite consultas de solo lectura. Confirma manualmente qué quieres buscar.",
        fecha_ambigua: "Confirma qué fecha quisiste indicar antes de buscar.",
        fechas_varias: "Se mencionan varias fechas. Revisa el intervalo antes de buscar.",
        fecha_incompleta: "Completa el año o el intervalo si quieres filtrar por fecha.",
        folios_varios: "Se mencionan varios folios. Especifica cuál quieres buscar.",
        referencias_varias: "Se mencionan varias referencias. Especifica cuál quieres consultar.",
        areas_varias: "Se mencionan varias áreas. Elige el departamento en los filtros.",
        area_no_disponible: "El criterio de área detectado no está disponible para tu cuenta.",
    };
    const revision = new Set(["negacion", "solo_lectura", "fecha_ambigua", "fechas_varias",
        "folios_varios", "referencias_varias", "areas_varias", "area_no_disponible"]);
    function liga({tipo, valor}) {
        if (typeof valor !== "string") return null;
        if (tipo === "registro" && /^[1-9]\d{0,17}$/.test(valor)) {
            return {url: "/documentos/" + valor, etiqueta: "Consultar registro " + valor};
        }
        if (tipo === "folio" && /^[A-Z0-9][A-Z0-9/-]{0,59}$/.test(valor)
                || tipo === "titulo" && valor.length > 0 && valor.length <= 90) {
            return {url: "/buscar?" + new URLSearchParams({q: valor}), etiqueta: "Buscar " + valor};
        }
        return null;
    }
    function fechaLocal(dias) {
        const d = new Date();
        d.setDate(d.getDate() + dias);
        return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"),
            String(d.getDate()).padStart(2, "0")].join("-");
    }

    window.sigedCrearApoyoClippy = function (panel, token) {
        let control = null;
        let bloqueado = false;
        function cancelar() {
            control?.abort();
            control = null;
            bloqueado = false;
            panel.replaceChildren();
            panel.hidden = true;
        }
        function linea(texto) {
            const p = document.createElement("p");
            p.textContent = texto;
            panel.append(p);
        }
        function boton(texto, accion) {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "boton-secundario";
            b.textContent = texto;
            b.addEventListener("click", accion);
            panel.append(b);
        }
        async function analizar(texto, {vigente, acepta, aplicar, esBusqueda, cubierto}) {
            cancelar();
            if (!token || !texto.trim() || texto.length > 300) return;
            const solicitud = new AbortController();
            control = solicitud;
            const plazo = setTimeout(() => solicitud.abort(), 1200);
            bloqueado = esBusqueda;
            const sinApoyo = () => {
                bloqueado = false;
                linea("El análisis adicional aún no está disponible. Puedes usar los criterios actuales.");
                boton("Reintentar análisis", () => analizar(texto, {vigente, acepta, aplicar, esBusqueda, cubierto}));
                panel.hidden = false;
            };
            try {
                const r = await fetch("/asistente/interpretar", {
                    method: "POST", credentials: "same-origin", redirect: "error", cache: "no-store",
                    headers: {"Content-Type": "application/json", "X-CSRF-Token": token},
                    body: JSON.stringify({texto}), signal: solicitud.signal,
                });
                if (control !== solicitud || !vigente()) return;
                const datos = r.status === 200 ? await r.json() : null;
                if (control !== solicitud || !vigente()) return;
                bloqueado = false;
                panel.replaceChildren();
                if (!datos) { sinApoyo(); return; }
                const avisos = (datos.avisos || []).filter(k => Object.hasOwn(mensajes, k));
                for (const k of avisos) linea(mensajes[k]);
                if (esBusqueda && avisos.some(k => revision.has(k) && !cubierto(k))) {
                    bloqueado = true;
                    boton("Ya revisé los criterios", () => {
                        if (control !== solicitud || !vigente()) return;
                        bloqueado = false;
                    });
                }
                const c = datos.criterios || {};
                const exacta = datos.dias_relativos === -2 ? fechaLocal(-2) : c.desde;
                const propuestas = [
                    ["Departamento", {departamento: c.departamento}],
                    ["Oficio", {oficio: c.oficio}],
                    ["Fecha", {desde: exacta, hasta: datos.dias_relativos === -2 ? exacta : c.hasta}],
                ];
                if (!avisos.some(k => revision.has(k))) {
                    for (const [nombre, filtros] of propuestas) {
                        if (!Object.values(filtros).every(v => typeof v === "string" && v) || !acepta(filtros)) continue;
                        boton("Usar " + nombre.toLowerCase() + " " + Object.values(filtros)[0], () => {
                            if (control === solicitud && vigente() && acepta(filtros)) {
                                aplicar(filtros, datos.consumir?.[Object.keys(filtros)[0]]);
                            }
                        });
                    }
                    for (const dato of datos.enlaces || []) {
                        const enlace = liga(dato);
                        if (!enlace) continue;
                        const a = document.createElement("a");
                        a.href = enlace.url;
                        a.textContent = enlace.etiqueta;
                        panel.append(a);
                    }
                }
                panel.hidden = !panel.childElementCount;
            } catch {
                if (control === solicitud && vigente()) { panel.replaceChildren(); sinApoyo(); }
            } finally {
                clearTimeout(plazo);
                if (control === solicitud && !vigente()) cancelar();
            }
        }
        return {analizar, cancelar, bloquea: () => bloqueado};
    };
})();

