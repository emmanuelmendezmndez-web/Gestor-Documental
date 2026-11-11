const TIPOS = new Set(["mensaje_nuevo", "lectura_actualizada", "bandeja_actualizada", "resincronizar"]);
const CURSOR = /^[0-9a-f]{32}\.[0-9a-f]{64}$/;
export const sesionInvalida = error => error.estado === 401 ||
    ["identidad_no_reconciliada", "generacion_cambio"].includes(error.message);

export function conectarMensajeria({ ruta, actualizar, cerrarSesion, informar }) {
    let socket, espera, inicio, lote, consulta;
    let cursor = null;
    let pendiente = false;
    let siguiente;
    let nuevo = false;
    let completo = false;
    let pausado = true;
    let terminado = false;
    let listo = false;
    let intentos = 0;
    const vistos = new Set();
    const ciclo = new AbortController();

    function desconectar() {
        clearTimeout(inicio);
        listo = false;
        const anterior = socket;
        socket = null;
        anterior?.close();
    }

    function pausar() {
        pausado = true;
        clearTimeout(espera);
        clearTimeout(lote);
        espera = lote = undefined;
        desconectar();
        consulta?.abort();
    }

    function detener(error) {
        if (terminado) return;
        terminado = true;
        pausar();
        ciclo.abort();
        vistos.clear();
        cursor = siguiente = null;
        if (error) cerrarSesion(error);
    }

    function reintentar() {
        if (pausado || terminado || espera !== undefined) return;
        const base = Math.min(24000, 1000 * 2 ** Math.min(intentos++, 5));
        espera = setTimeout(() => {
            espera = undefined;
            invalidar(true);
            abrir();
        }, base * (0.75 + Math.random() * 0.5));
    }

    async function aplicar() {
        lote = undefined;
        if (!pendiente || consulta || pausado) return;
        pendiente = false;
        const candidato = siguiente;
        const aviso = nuevo;
        const reconstruir = completo;
        nuevo = completo = false;
        const peticion = new AbortController();
        consulta = peticion;
        const canal = listo ? socket : null;
        try {
            const aplicado = await actualizar({ nuevo: aviso, completo: reconstruir, signal: peticion.signal });
            if (peticion.signal.aborted) return;
            if (aplicado === false) {
                nuevo ||= aviso;
                invalidar(reconstruir);
                return;
            }
            if (candidato !== undefined) cursor = candidato;
            if (canal && canal === socket) intentos = 0;
        } catch (error) {
            if (peticion.signal.aborted) return;
            if (sesionInvalida(error) || [403, 404].includes(error.estado)) {
                detener(error);
                return;
            }
            informar(error);
            nuevo ||= aviso;
            completo ||= reconstruir;
            pendiente = true;
            desconectar();
            reintentar();
        } finally {
            if (peticion.signal.aborted && !terminado) {
                nuevo ||= aviso;
                completo ||= reconstruir;
                pendiente = true;
            }
            consulta = null;
            programar();
        }
    }

    function programar() {
        if (pendiente && !pausado && !consulta && espera === undefined && lote === undefined) {
            lote = setTimeout(aplicar, 60);
        }
    }

    function invalidar(reconstruir = false) {
        if (terminado) return;
        pendiente = true;
        completo ||= reconstruir;
        programar();
    }

    function abrir() {
        if (!ruta || socket || pausado || navigator.onLine === false) return;
        const url = new URL(ruta, location.origin);
        if (url.origin !== location.origin || !["http:", "https:"].includes(url.protocol)) return;
        url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
        let canal;
        try {
            canal = new WebSocket(url);
        } catch {
            reintentar();
            return;
        }
        socket = canal;
        inicio = setTimeout(() => {
            desconectar();
            reintentar();
        }, 16000);
        canal.addEventListener("message", ({ data }) => {
            if (socket !== canal || typeof data !== "string" || data.length > 1024) return;
            let evento;
            try { evento = JSON.parse(data); } catch { return; }
            if (evento?.tipo === "conexion_lista" && !listo) {
                clearTimeout(inicio);
                listo = true;
                canal.send(JSON.stringify({ tipo: "sincronizar", cursor }));
                invalidar(true);
                return;
            }
            if (!listo || !TIPOS.has(evento?.tipo)) return;
            const token = evento.cursor;
            const reiniciar = evento.tipo === "resincronizar";
            if (!(reiniciar && token === null) && !(typeof token === "string" && CURSOR.test(token))) return;
            if (!reiniciar && (token === cursor || vistos.has(token))) return;
            if (reiniciar) vistos.clear();
            if (token !== null) vistos.add(token);
            if (vistos.size > 128) vistos.delete(vistos.values().next().value);
            siguiente = token;
            nuevo ||= evento.tipo === "mensaje_nuevo";
            invalidar(reiniciar || evento.tipo === "lectura_actualizada");
        });
        canal.addEventListener("close", ({ code }) => {
            if (socket !== canal) return;
            desconectar();
            if (code === 1008 || code === 1009) {
                const error = new Error("canal_no_disponible");
                error.estado = code === 1008 ? 401 : 403;
                detener(error);
                return;
            }
            // Un rechazo anterior al Upgrade se observa como 1006. HTTP confirma
            // si la sesión sigue autorizada en el siguiente intento.
            reintentar();
        });
    }

    function reanudar() {
        if (terminado || !pausado) return;
        pausado = false;
        invalidar(true);
        abrir();
    }

    function recuperar() {
        if (pausado || terminado) return;
        invalidar(true);
        if (espera === undefined) abrir();
    }

    const opciones = { signal: ciclo.signal };
    window.addEventListener("pagehide", pausar, opciones);
    window.addEventListener("pageshow", reanudar, opciones);
    window.addEventListener("online", recuperar, opciones);
    window.addEventListener("offline", () => {
        desconectar();
        if (!pausado) reintentar();
    }, opciones);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) recuperar();
    }, opciones);
    reanudar();
    return { invalidar, detener };
}
