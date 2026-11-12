import {
    API, LIMITE, ErrorHTTP, buscarDocumentos, caracteres, claveEnvio, enviar, formato, mensajeError,
    pedir, plazoPeticion, referencia, textoValido,
} from "./mensajeria_transporte.mjs?v=2";
import { conectarMensajeria, sesionInvalida } from "./mensajeria_tiempo_real.mjs";

const porId = id => document.getElementById(id);
const raiz = porId("mensajeria");
const campana = porId("mensajeria-campana");
const indicador = document.querySelector("[data-mensajeria-no-leidos]");
const numero = n => n > 99 ? "99+" : String(n);

function mostrarContador(total) {
    indicador.hidden = !total;
    indicador.textContent = total ? numero(total) : "";
    indicador.parentElement.setAttribute("aria-label", total ?
        "Mensajería, " + total + " mensajes sin leer" : "Mensajería");
}

function desplegable(detalle) {
    document.addEventListener("pointerdown", evento => {
        if (detalle.open && !detalle.contains(evento.target)) detalle.open = false;
    });
    detalle.addEventListener("keydown", evento => {
        if (evento.key === "Escape" && detalle.open) {
            detalle.open = false;
            detalle.querySelector("summary").focus();
        }
    });
}

function iniciarAvisos() {
    const controlCampana = campana.querySelector("summary");
    const badge = campana.querySelector("[data-mensajeria-avisos]");
    const estado = campana.querySelector("[data-mensajeria-estado-avisos]");
    const lista = campana.querySelector("[data-mensajeria-lista-avisos]");
    const avisoDisco = lista.querySelector("[data-aviso-almacenamiento] a");
    avisoDisco?.addEventListener("click", evento => {
        if (!evento.ctrlKey && !evento.metaKey && !evento.shiftKey && !evento.altKey) campana.open = false;
    });
    const vivo = document.querySelector("[data-mensajeria-aviso-vivo]");
    const plantilla = porId("mensajeria-aviso-pendiente");
    const filas = new Map();
    const anunciados = new Set();
    let consultado = false;
    return function mostrarAvisos(avisos, nuevo = false, error = "") {
        const textos = avisos.map(({ nombre }) => nombre ? "Nuevo mensaje de " + nombre : "Nuevo mensaje recibido");
        const novedad = nuevo && consultado ? avisos.findIndex(aviso => !anunciados.has(aviso.mensaje)) : -1;
        vivo.textContent = textos[novedad] || "";
        if (novedad >= 0) controlCampana.dispatchEvent(new Event("animar-icono", { bubbles: true }));
        const presentes = new Set();
        let anterior = null;
        for (const aviso of avisos) {
            anunciados.add(aviso.mensaje);
            if (anunciados.size > 128) anunciados.delete(anunciados.values().next().value);
            presentes.add(aviso.mensaje);
            let fila = filas.get(aviso.mensaje);
            if (!fila) {
                fila = plantilla.content.firstElementChild.cloneNode(true);
                const enlace = fila.querySelector("a");
                enlace.href = "/mensajeria";
                if (referencia(aviso.conversacion)) {
                    enlace.dataset.conversacion = aviso.conversacion;
                    enlace.href += "?conversacion=" + aviso.conversacion;
                }
                if (Number.isSafeInteger(aviso.confirmado_utc) && aviso.confirmado_utc > 0) {
                    enlace.querySelector(".mensajeria-notificacion-texto").append(hora(aviso.confirmado_utc, true));
                }
                filas.set(aviso.mensaje, fila);
            }
            fila.querySelector("[data-remitente]").textContent = aviso.nombre || "Usuario no disponible";
            const siguiente = anterior ? anterior.nextElementSibling : lista.firstElementChild;
            if (siguiente !== fila) lista.insertBefore(fila, siguiente);
            anterior = fila;
        }
        for (const [id, fila] of filas) {
            if (presentes.has(id)) continue;
            if (fila.contains(document.activeElement)) controlCampana.focus();
            fila.remove();
            filas.delete(id);
        }
        consultado = !error;
        if (error) anunciados.clear();
        const total = avisos.length + Number(Boolean(avisoDisco));
        estado.hidden = total > 0 && !error;
        estado.textContent = error || "No tienes notificaciones pendientes.";
        badge.hidden = !total;
        badge.textContent = total ? numero(total) : "";
        controlCampana.setAttribute("aria-label",
            total ? "Notificaciones, " + total + (total === 1 ? " aviso pendiente" : " avisos pendientes") : "Notificaciones");
    };
}

if (campana) {
    desplegable(campana);
    const mostrarAvisos = iniciarAvisos();
    if (raiz) iniciarMensajeria(raiz, mostrarAvisos);
    else {
        const canal = conectarMensajeria({
            ruta: campana.dataset.rutaWs,
            async actualizar({ nuevo, signal }) {
                const datos = await pedir("/sincronizacion?limite=1&avisos=true", {
                    signal, plazo: 20000,
                });
                if (signal.aborted) return;
                mostrarContador(datos.no_leidos);
                mostrarAvisos(datos.avisos ?? [], nuevo);
            },
            cerrarSesion(error) {
                mostrarContador(0);
                mostrarAvisos([], false, mensajeError(error));
            },
            informar() {},
        });
        campana.addEventListener("toggle", () => { if (campana.open) canal.invalidar(); });
    }
}

function crear(etiqueta, clase, texto) {
    const elemento = document.createElement(etiqueta);
    if (clase) elemento.className = clase;
    if (texto !== undefined) elemento.textContent = texto;
    return elemento;
}

function boton(texto, clase) {
    const elemento = crear("button", clase, texto);
    elemento.type = "button";
    return elemento;
}

function iniciales(nombre) {
    const palabras = nombre.trim().split(/\s+/);
    return (palabras.length > 1 ? [palabras[0], palabras[palabras.length - 1]] : palabras)
        .map(palabra => Array.from(palabra)[0] || "").join("").toLocaleUpperCase("es");
}

const normalizar = texto => texto.normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase("es");
const perfil = persona => normalizar(persona.nombre + "|" + (persona.area || ""));
function contarPerfiles(personas) {
    const frecuencias = new Map();
    for (const persona of personas) {
        const clave = perfil(persona);
        frecuencias.set(clave, (frecuencias.get(clave) || 0) + 1);
    }
    return frecuencias;
}

function perfilSecundario(persona, frecuencias) {
    const codigo = frecuencias.get(perfil(persona)) > 1 ? persona.referencia.slice(-8) : "";
    return [persona.area, codigo].filter(Boolean).join(" · ");
}

const reloj = new Intl.DateTimeFormat("es-MX", { hour: "numeric", minute: "2-digit" });
const calendario = new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "short" });
const fechaCompleta = new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" });
function hora(segundos, corta = false) {
    const fecha = new Date(segundos * 1000);
    const elemento = crear("time", corta ? "" : "mensajeria-hora",
        corta && fecha.toDateString() !== new Date().toDateString() ? calendario.format(fecha) : reloj.format(fecha));
    elemento.dateTime = fecha.toISOString();
    elemento.title = fechaCompleta.format(fecha);
    return elemento;
}

function tamano(bytes) {
    const unidad = bytes >= 1048576 ? [1048576, "MiB"] : bytes >= 1024 ? [1024, "KiB"] : [1, "B"];
    return new Intl.NumberFormat("es-MX", { maximumFractionDigits: 1 }).format(bytes / unidad[0]) + " " + unidad[1];
}

function icono(nombre) {
    const tipo = porId("mensajeria-formato-" + formato(nombre));
    return (tipo || porId("mensajeria-formato-archivo")).content.cloneNode(true);
}

function iniciarMensajeria(raiz, mostrarAvisos) {
    const el = nombre => porId("mensajeria-" + nombre);
    const lista = el("conversaciones");
    const historial = el("historial");
    const shell = raiz.closest(".app-shell");
    const mensajes = el("mensajes");
    const dialogo = el("selector");
    const opciones = el("opciones");
    const texto = el("texto");
    const acciones = el("acciones");
    const movil = matchMedia("(max-width: 800px)");
    const chats = new Map();
    const filasChat = new Map();
    const visibles = new Map();
    const borradores = new Map();
    let cursorChats, cursorMensajes, activo, cuota, adjunto, operacion;
    let peticionLista, peticionChat, peticionSelector, peticionApertura, selector;
    let archivadas = false;
    let enviando = false;
    let marcando = false;
    let archivando = false;
    let falloSesion = false;
    let venceTarjeta, ocultarAviso;
    let paginasChats = 1;
    let paginandoChats, paginandoMensajes;
    let lecturaProgramada = false;
    const exposicion = new IntersectionObserver(programarLectura, { threshold: [0, 0.5] });

    function programarLectura() {
        if (lecturaProgramada || marcando || !activo?.id) return;
        lecturaProgramada = true;
        requestAnimationFrame(() => {
            lecturaProgramada = false;
            marcarLectura(true);
        });
    }

    function limpiarVisibles() {
        exposicion.disconnect();
        visibles.clear();
    }

    function textoVisible(fila) {
        if (document.hidden || !document.hasFocus() || dialogo.open || !fila.texto.isConnected) return false;
        const mensaje = fila.texto.getBoundingClientRect();
        const zona = historial.getBoundingClientRect();
        const viewport = window.visualViewport;
        const arriba = viewport?.offsetTop ?? 0;
        const izquierda = viewport?.offsetLeft ?? 0;
        const alto = Math.min(mensaje.bottom, zona.bottom, arriba + (viewport?.height ?? innerHeight))
            - Math.max(mensaje.top, zona.top, arriba);
        const ancho = Math.min(mensaje.right, zona.right, izquierda + (viewport?.width ?? innerWidth))
            - Math.max(mensaje.left, zona.left, izquierda);
        return mensaje.height > 0 && alto >= mensaje.height / 2 && ancho > 0;
    }

    desplegable(acciones);

    function anunciar(mensaje, error = false) {
        const aviso = el("aviso");
        window.clearTimeout(ocultarAviso);
        delete aviso.dataset.salida;
        aviso.dataset.tipo = error ? "error" : "exito";
        el("aviso-texto").textContent = mensaje;
        el("aviso-estado").textContent = error ? "" : mensaje;
        el("aviso-error").textContent = error ? mensaje : "";
        aviso.hidden = !mensaje;
        if (!mensaje) return;
        ocultarAviso = window.setTimeout(() => {
            if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
                aviso.hidden = true;
                return;
            }
            aviso.dataset.salida = "";
            ocultarAviso = window.setTimeout(() => { aviso.hidden = true; }, 250);
        }, error ? Math.max(7000, Math.min(16000, mensaje.length * 55)) : 2600);
    }

    function guardarCuota(datos) {
        cuota = datos;
        el("cuota").textContent = cuota.restantes + " de " + cuota.limite + " envíos disponibles";
        controles();
    }

    function fallo(error, cerrar = false) {
        if (cerrar || sesionInvalida(error)) {
            falloSesion = true;
            chats.clear();
            filasChat.clear();
            lista.replaceChildren();
            mensajes.replaceChildren();
            limpiarVisibles();
            el("estado-lista").textContent = mensajeError(error);
            el("mas-chats").hidden = true;
            el("reintentar-lista").hidden = true;
            el("mas-mensajes").hidden = true;
            el("reintentar-historial").hidden = true;
            el("chat-titulo").textContent = "Mensajería no disponible";
            el("chat-avatar").textContent = "";
            el("chat-area").hidden = true;
            acciones.hidden = true;
            if (dialogo.open) {
                opciones.replaceChildren();
                el("mas-opciones").hidden = true;
            }
            mostrarContador(0);
            mostrarAvisos([], false, mensajeError(error));
            el("cuota").textContent = "";
            peticionLista?.abort();
            peticionChat?.abort();
            peticionSelector?.abort();
            peticionApertura?.abort();
            canal.detener();
            window.clearTimeout(venceTarjeta);
            controles();
        }
        return mensajeError(error);
    }

    function pintarBandeja() {
        const termino = normalizar(el("buscar").value.trim());
        const orden = [...chats.values()].sort((a, b) =>
            (b.ultimo?.confirmado_utc || 0) - (a.ultimo?.confirmado_utc || 0) || a.id.localeCompare(b.id));
        const frecuencias = contarPerfiles(orden.map(chat => chat.otro).filter(Boolean));
        let anterior = null;
        let cantidad = 0;
        for (const chat of orden) {
            let fila = filasChat.get(chat.id);
            if (!fila) {
                const entrada = boton("", "");
                const avatar = crear("span", "mensajeria-avatar");
                avatar.setAttribute("aria-hidden", "true");
                const identidad = crear("span", "mensajeria-fila-texto");
                const nombre = crear("strong");
                const resumen = crear("small");
                identidad.append(nombre, resumen);
                const datos = crear("span", "mensajeria-fila-datos");
                entrada.append(avatar, identidad, datos);
                const item = crear("li");
                item.append(entrada);
                entrada.addEventListener("click", () => abrirChat(chats.get(chat.id)));
                fila = { item, entrada, avatar, nombre, resumen, datos };
                filasChat.set(chat.id, fila);
            }
            const nombre = chat.otro?.nombre || "Usuario no disponible";
            const area = chat.otro ? perfilSecundario(chat.otro, frecuencias) : "";
            const coincide = normalizar([nombre, area, chat.ultimo?.texto || ""].join(" ")).includes(termino);
            fila.item.hidden = !coincide;
            if (coincide) cantidad++;
            fila.entrada.setAttribute("aria-current", String(activo?.id === chat.id));
            fila.avatar.textContent = iniciales(nombre);
            fila.nombre.textContent = nombre;
            fila.resumen.textContent = [area, chat.ultimo?.texto].filter(Boolean).join(" · ") || "Sin mensajes recientes";
            fila.entrada.setAttribute("aria-label", [nombre, area, chat.no_leidos ? chat.no_leidos + " sin leer" : ""]
                .filter(Boolean).join(", "));
            fila.datos.replaceChildren();
            if (chat.ultimo) fila.datos.append(hora(chat.ultimo.confirmado_utc, true));
            if (chat.no_leidos) fila.datos.append(crear("small", "mensajeria-contador", numero(chat.no_leidos)));
            const siguiente = anterior ? anterior.nextElementSibling : lista.firstElementChild;
            if (siguiente !== fila.item) lista.insertBefore(fila.item, siguiente);
            anterior = fila.item;
        }
        el("mas-chats").hidden = !cursorChats;
        el("estado-lista").textContent = cantidad ? "" : termino ?
            (cursorChats ? "Sin coincidencias en esta página. Puedes cargar más conversaciones." : "No hay coincidencias.") :
            archivadas ? "No tienes conversaciones archivadas." : "Aún no tienes conversaciones. Inicia una con el botón superior.";
    }

    function vaciarBandeja() {
        chats.clear();
        filasChat.clear();
        lista.replaceChildren();
        cursorChats = undefined;
        paginasChats = 1;
    }

    async function cargarBandeja(mas = false, conservar = false, sincronizacion) {
        if (falloSesion) return;
        peticionLista?.abort();
        const peticion = new AbortController();
        peticionLista = peticion;
        const { signal, liberar } = plazoPeticion(20000, peticion.signal, sincronizacion?.signal);
        const filtro = new URLSearchParams({ archivadas });
        if (!mas) filtro.set("avisos", "true");
        if (mas && cursorChats) filtro.set("despues", cursorChats);
        el("reintentar-lista").hidden = true;
        el("mas-chats").disabled = true;
        if (!chats.size) el("estado-lista").textContent = "Cargando conversaciones…";
        try {
            const datos = await pedir((mas ? "/conversaciones?" : "/sincronizacion?") + filtro, { signal });
            let pagina = mas ? datos : datos.conversaciones;
            const elementos = [...pagina.elementos];
            if (conservar) {
                filtro.delete("avisos");
                for (let n = 1; n < paginasChats && pagina.siguiente; n++) {
                    filtro.set("despues", pagina.siguiente);
                    pagina = await pedir("/conversaciones?" + filtro, { signal });
                    elementos.push(...pagina.elementos);
                }
            }
            if (peticion.signal.aborted || sincronizacion?.signal.aborted) return false;
            if (!mas) {
                mostrarContador(datos.no_leidos);
                mostrarAvisos(datos.avisos ?? [], sincronizacion?.nuevo);
                guardarCuota(datos.cuota);
                const ids = new Set(elementos.map(chat => chat.id));
                for (const id of chats.keys()) {
                    if (ids.has(id)) continue;
                    filasChat.get(id)?.item.remove();
                    filasChat.delete(id);
                    chats.delete(id);
                }
            }
            if (mas) paginasChats++;
            else if (!conservar) paginasChats = 1;
            elementos.forEach(chat => chats.set(chat.id, chat));
            cursorChats = pagina.siguiente;
            pintarBandeja();
            return true;
        } catch (error) {
            if (peticion.signal.aborted || sincronizacion?.signal.aborted) return false;
            if (sincronizacion) throw error;
            el("estado-lista").textContent = fallo(error);
            el("reintentar-lista").hidden = false;
        } finally {
            liberar();
            if (peticionLista === peticion) el("mas-chats").disabled = false;
        }
    }

    function seleccionChat(chat) {
        return chat?.otro || { nombre: "Usuario no disponible", area: "" };
    }

    function limpiarEnlaceChat(id) {
        const ubicacion = new URL(location.href);
        if (ubicacion.searchParams.has("conversacion") && ubicacion.searchParams.get("conversacion") !== id) {
            ubicacion.searchParams.delete("conversacion");
            history.replaceState(history.state, "", ubicacion);
        }
    }

    function abrirChat(chat, conservar = false) {
        if (!chat || falloSesion || enviando || (operacion?.incierta && !conservar)) return;
        peticionApertura?.abort();
        if (activo?.id && activo.id === chat.id && !conservar) return;
        peticionChat?.abort();
        window.clearTimeout(venceTarjeta);
        acciones.open = false;
        if (!conservar) {
            guardarBorrador();
            limpiarCompositor();
        }
        activo = chat;
        limpiarEnlaceChat(chat.id);
        if (!conservar) {
            const clave = chat.otro?.referencia;
            const borrador = borradores.get(clave);
            if (borrador) {
                borradores.delete(clave);
                texto.value = borrador.texto;
                elegirAdjunto(borrador.adjunto);
                operacion = borrador.operacion;
            }
        }
        cursorMensajes = null;
        limpiarVisibles();
        mensajes.replaceChildren();
        el("estado-historial").textContent = "";
        el("mas-mensajes").hidden = true;
        el("reintentar-historial").hidden = true;
        const persona = seleccionChat(chat);
        el("chat-titulo").textContent = persona.nombre;
        el("chat-avatar").textContent = iniciales(persona.nombre);
        el("chat-area").textContent = persona.area || "";
        el("chat-area").hidden = !persona.area;
        el("archivar").textContent = chat.archivada ? "Mover a activas" : "Archivar conversación";
        acciones.hidden = !chat.id;
        raiz.dataset.abierta = "";
        raiz.querySelector(".mensajeria-bienvenida").hidden = true;
        raiz.querySelector(".mensajeria-chat").hidden = false;
        pintarBandeja();
        controles();
        el("chat-titulo").focus({ preventScroll: true });
        if (chat.id) cargarHistorial();
        else el("estado-historial").textContent = "Escribe y adjunta un archivo para iniciar la conversación.";
    }

    function volver(foco = true) {
        if (enviando || operacion?.incierta) return;
        guardarBorrador();
        const seleccionado = activo;
        activo = null;
        limpiarEnlaceChat();
        acciones.open = false;
        peticionApertura?.abort();
        peticionChat?.abort();
        window.clearTimeout(venceTarjeta);
        limpiarVisibles();
        mensajes.replaceChildren();
        limpiarCompositor();
        delete raiz.dataset.abierta;
        raiz.querySelector(".mensajeria-bienvenida").hidden = false;
        raiz.querySelector(".mensajeria-chat").hidden = true;
        pintarBandeja();
        if (foco) (filasChat.get(seleccionado?.id)?.entrada || el("bandeja-titulo")).focus();
    }

    function burbuja(mensaje) {
        const saliente = mensaje.enviado;
        const item = crear("li", "mensajeria-mensaje" + (saliente ? " enviado" : ""));
        item.dataset.mensaje = mensaje.id;
        const cuerpo = crear("div", "mensajeria-burbuja");
        cuerpo.append(crear("span", "sr-only", saliente ? "Enviado" : "Recibido"));
        const textoMensaje = crear("p", "mensajeria-texto", mensaje.texto);
        cuerpo.append(textoMensaje);
        const tarjeta = crear("div", "mensajeria-tarjeta", "Comprobando adjunto…");
        cuerpo.append(tarjeta, hora(mensaje.confirmado_utc));
        item.append(cuerpo);
        const datos = { mensaje, item, tarjeta, texto: textoMensaje, vence: null };
        visibles.set(mensaje.id, datos);
        if (!saliente && !mensaje.leido_utc) exposicion.observe(textoMensaje);
        return datos;
    }

    function tarjetaNoDisponible(fila) {
        fila.vence = null;
        fila.tarjeta.textContent = "Documento no disponible";
    }

    function tarjetaPorComprobar(fila, chat) {
        fila.vence = null;
        const comprobar = boton("Comprobar adjunto", "mensajeria-secundario");
        comprobar.addEventListener("click", () => {
            comprobar.disabled = true;
            comprobarTarjetas([fila], chat, peticionChat.signal);
        });
        fila.tarjeta.replaceChildren(comprobar);
    }

    function pintarTarjeta(fila, datos, chat) {
        if (datos.estado !== "disponible" || datos.vence_utc * 1000 <= Date.now()) {
            tarjetaNoDisponible(fila);
            return;
        }
        fila.vence = datos.vence_utc * 1000;
        const nombre = datos.nombre_original;
        const detalle = crear("span", "mensajeria-archivo-datos");
        const origen = datos.origen === "biblioteca" ? "Biblioteca" : "Archivo externo";
        const vence = "Disponible hasta " + fechaCompleta.format(new Date(fila.vence));
        detalle.append(crear("strong", "", nombre), crear("small", "",
            [origen, datos.tamano_bytes ? tamano(datos.tamano_bytes) : "", vence].filter(Boolean).join(" · ")));
        fila.tarjeta.replaceChildren(icono(nombre), detalle);
        const ruta = API + "/conversaciones/" + chat + "/mensajes/" + fila.mensaje.id + "/adjunto/";
        const acciones = crear("span", "mensajeria-archivo-acciones");
        for (const [accion, etiqueta, destino] of [
            ["visualizar", "Visualizar", "vista"], ["descargar", "Descargar", "descarga"],
        ]) {
            if (!datos.acciones.includes(accion)) continue;
            const enlace = crear("a", "", etiqueta);
            enlace.href = ruta + destino;
            enlace.setAttribute("aria-label", etiqueta + " " + nombre + (accion === "visualizar" ? " (nueva pestaña)" : ""));
            if (accion === "visualizar") {
                enlace.target = "_blank";
                enlace.rel = "noopener noreferrer";
            } else {
                enlace.download = "";
            }
            acciones.append(enlace);
        }
        if (acciones.childElementCount) fila.tarjeta.append(acciones);
        if (!datos.acciones.includes("visualizar")) {
            detalle.append(crear("small", "", "Vista previa no disponible para este archivo o modalidad."));
        }
    }

    function programarVencimientos() {
        window.clearTimeout(venceTarjeta);
        const ahora = Date.now();
        let proximo = Infinity;
        for (const [id, fila] of visibles) {
            const venceMensaje = fila.mensaje.historial_vence_utc * 1000;
            if (venceMensaje <= ahora) {
                fila.item.remove();
                exposicion.unobserve(fila.texto);
                visibles.delete(id);
                continue;
            }
            proximo = Math.min(proximo, venceMensaje);
            if (!fila.vence) continue;
            if (fila.vence <= ahora) tarjetaNoDisponible(fila);
            else proximo = Math.min(proximo, fila.vence);
        }
        if (!visibles.size && activo?.id && !falloSesion) {
            el("estado-historial").textContent = "No hay mensajes en el historial de los últimos 15 días.";
        }
        controles();
        if (Number.isFinite(proximo)) venceTarjeta = window.setTimeout(programarVencimientos, Math.max(1, proximo - Date.now()));
    }

    async function comprobarTarjetas(filas, chat, signal) {
        const cola = filas.values();
        async function comprobar() {
            for (const fila of cola) {
                if (signal.aborted) break;
                try {
                    const datos = await pedir("/conversaciones/" + chat + "/mensajes/" + fila.mensaje.id + "/adjunto", { signal });
                    if (!signal.aborted) pintarTarjeta(fila, datos, chat);
                } catch (error) {
                    if (signal.aborted) break;
                    tarjetaNoDisponible(fila);
                    if (sesionInvalida(error)) {
                        el("estado-historial").textContent = fallo(error);
                        break;
                    }
                }
            }
        }
        await Promise.all(Array.from({ length: Math.min(filas.length, 4) }, comprobar));
        if (!signal.aborted) programarVencimientos();
    }

    async function cargarHistorial(mas = false, actualizar = false, sincronizacion) {
        const chat = activo?.id;
        if (!referencia(chat) || falloSesion) return true;
        peticionChat?.abort();
        const peticion = new AbortController();
        peticionChat = peticion;
        const { signal, liberar } = plazoPeticion(60000, peticion.signal, sincronizacion?.signal);
        const filtro = new URLSearchParams({ limite: 20 });
        if (mas && cursorMensajes) filtro.set("antes", cursorMensajes);
        el("reintentar-historial").hidden = true;
        el("mas-mensajes").disabled = true;
        if (!visibles.size) el("estado-historial").textContent = "Cargando historial…";
        try {
            const ruta = "/conversaciones/" + chat + "/mensajes?";
            let pagina = await pedir(ruta + filtro, { signal });
            const elementos = [...pagina.elementos];
            if (actualizar && visibles.size) {
                const limite = sincronizacion?.completo ? mensajes.firstElementChild?.dataset.mensaje : null;
                const alcanza = mensaje => limite ? mensaje.id === limite : visibles.has(mensaje.id);
                while (pagina.siguiente && !pagina.elementos.some(alcanza)) {
                    filtro.set("antes", pagina.siguiente);
                    pagina = await pedir(ruta + filtro, { signal });
                    elementos.push(...pagina.elementos);
                }
                if (limite) {
                    const indice = elementos.findIndex(alcanza);
                    if (indice >= 0) elementos.length = indice + 1;
                }
            }
            if (peticion.signal.aborted || sincronizacion?.signal.aborted) return false;
            const previamente = historial.scrollHeight;
            const abajo = historial.scrollHeight - historial.scrollTop - historial.clientHeight < 60;
            if (!actualizar || !visibles.size) cursorMensajes = pagina.siguiente;
            const filas = [];
            for (const mensaje of elementos.reverse()) {
                if (!referencia(mensaje.id)) continue;
                const previa = visibles.get(mensaje.id);
                if (previa) {
                    // Una respuesta iniciada antes del POST puede llegar después de su confirmación.
                    mensaje.leido_utc ||= previa.mensaje.leido_utc;
                    previa.mensaje = mensaje;
                    if (mensaje.leido_utc) exposicion.unobserve(previa.texto);
                    if (!previa.vence) filas.push(previa);
                    continue;
                }
                filas.push(burbuja(mensaje));
            }
            const orden = [...visibles.values()].sort((a, b) =>
                a.mensaje.confirmado_utc - b.mensaje.confirmado_utc || a.mensaje.id.localeCompare(b.mensaje.id));
            let anterior = null;
            for (const fila of orden) {
                const siguiente = anterior ? anterior.nextElementSibling : mensajes.firstElementChild;
                if (siguiente !== fila.item) mensajes.insertBefore(fila.item, siguiente);
                anterior = fila.item;
            }
            el("estado-historial").textContent = visibles.size ? "" : "No hay mensajes en el historial de los últimos 15 días.";
            el("mas-mensajes").hidden = !cursorMensajes;
            controles();
            if (mas) historial.scrollTop += historial.scrollHeight - previamente;
            else if (!actualizar || abajo) historial.scrollTop = historial.scrollHeight;
            const posicion = historial.scrollTop;
            programarLectura();
            await comprobarTarjetas(filas, chat, signal);
            if (signal.aborted && !peticion.signal.aborted && !sincronizacion?.signal.aborted) throw new ErrorHTTP(0);
            if (!signal.aborted && !mas && (!actualizar || abajo) && historial.scrollTop >= posicion - 4) {
                historial.scrollTop = historial.scrollHeight;
            }
            return !signal.aborted;
        } catch (error) {
            if (peticion.signal.aborted || sincronizacion?.signal.aborted) return false;
            if (error.estado === 404 && sincronizacion) {
                limpiarVisibles();
                mensajes.replaceChildren();
                cursorMensajes = null;
                el("mas-mensajes").hidden = true;
                el("estado-historial").textContent = mensajeError(error);
                controles();
                return true;
            }
            if (sincronizacion) throw error;
            el("estado-historial").textContent = fallo(error);
            el("reintentar-historial").hidden = false;
        } finally {
            liberar();
            if (peticionChat === peticion) el("mas-mensajes").disabled = false;
        }
    }

    function controles() {
        const bloqueado = enviando || operacion?.incierta;
        const longitud = caracteres(texto.value);
        const destinatario = activo?.otro?.referencia;
        el("caracteres").textContent = longitud + " / 300";
        texto.setAttribute("aria-invalid", String(longitud > 300));
        texto.disabled = Boolean(bloqueado || falloSesion || !destinatario);
        for (const nombre of ["adjuntar", "biblioteca"]) el(nombre).disabled = texto.disabled;
        const quitar = el("adjunto-elegido").querySelector("button");
        if (quitar) quitar.disabled = texto.disabled;
        const modalidad = el("adjunto-elegido").querySelector("select");
        if (modalidad) modalidad.disabled = texto.disabled;
        el("nuevo").disabled = Boolean(bloqueado || falloSesion);
        el("volver").disabled = Boolean(bloqueado);
        el("cerrar-chat").disabled = Boolean(bloqueado);
        el("archivar").disabled = Boolean(bloqueado || archivando || falloSesion);
        el("leer").hidden = ![...visibles.values()].some(({ mensaje }) =>
            !mensaje.leido_utc && !mensaje.enviado);
        el("leer").disabled = Boolean(bloqueado || marcando || falloSesion);
        el("descartar").hidden = !operacion?.incierta || enviando;
        const enviarBoton = el("enviar");
        const etiqueta = enviando ? "Enviando…" : operacion ? "Reintentar" : "Enviar";
        if (el("enviar-texto").textContent !== etiqueta) el("enviar-texto").textContent = etiqueta;
        enviarBoton.querySelector(".mensajeria-envio-giro").hidden = !enviando;
        if (enviando) enviarBoton.setAttribute("aria-busy", "true");
        else enviarBoton.removeAttribute("aria-busy");
        el("enviar").disabled = Boolean(enviando || archivando || falloSesion || !destinatario || !adjunto || !textoValido(texto.value) ||
            (cuota?.restantes === 0 && !operacion?.incierta));
    }

    function elegirAdjunto(elegido) {
        adjunto = elegido;
        operacion = null;
        const contenedor = el("adjunto-elegido");
        contenedor.replaceChildren();
        contenedor.hidden = !elegido;
        if (elegido) {
            const tarjeta = crear("div", "mensajeria-tarjeta");
            const archivo = elegido.archivo;
            const nombre = archivo ? archivo.name : elegido.nombre;
            const datos = crear("span", "mensajeria-archivo-datos");
            const descripcion = archivo ? formato(nombre).toUpperCase() + " · " + tamano(archivo.size) :
                elegido.modalidad === "visualizar" ? "Biblioteca · Solo visualizar" : "Biblioteca";
            datos.append(crear("strong", "", nombre), crear("small", "", descripcion));
            if (elegido.soloVista && elegido.descarga) {
                const modalidad = crear("select");
                modalidad.setAttribute("aria-label", "Modalidad de acceso del adjunto");
                for (const [valor, etiqueta] of [
                    ["visualizar_y_descargar", "Visualizar y descargar"], ["visualizar", "Solo visualizar"],
                ]) {
                    const opcion = crear("option", "", etiqueta);
                    opcion.value = valor;
                    modalidad.append(opcion);
                }
                modalidad.value = elegido.modalidad;
                modalidad.addEventListener("change", () => {
                    elegido.modalidad = modalidad.value;
                    operacion = null;
                });
                datos.append(modalidad);
            }
            const quitar = boton("Quitar", "mensajeria-secundario");
            quitar.setAttribute("aria-label", "Quitar adjunto");
            quitar.addEventListener("click", () => { elegirAdjunto(null); el("adjuntar").focus(); });
            tarjeta.append(icono(nombre), datos, quitar);
            contenedor.append(tarjeta);
        }
        controles();
    }

    function guardarBorrador() {
        const clave = activo?.otro?.referencia;
        if (!clave) return;
        if (texto.value || adjunto) borradores.set(clave, { texto: texto.value, adjunto, operacion });
        else borradores.delete(clave);
    }

    function limpiarCompositor() {
        texto.value = "";
        elegirAdjunto(null);
        anunciar("");
        estadoEnvio(null);
    }

    function estadoEnvio(etapa) {
        const estado = el("fase-envio");
        if (estado.textContent !== (etapa || "")) estado.textContent = etapa || "";
    }

    async function buscarConversacion(coincide, signal) {
        for (const bandeja of [archivadas, !archivadas]) {
            let despues = null;
            do {
                const filtro = new URLSearchParams({ archivadas: bandeja, limite: 50 });
                if (despues) filtro.set("despues", despues);
                const pagina = await pedir("/conversaciones?" + filtro, { signal });
                const encontrada = pagina.elementos.find(coincide);
                if (encontrada) return encontrada;
                despues = pagina.siguiente;
            } while (despues);
        }
        return null;
    }

    async function abrirConversacionAviso(id) {
        if (!referencia(id) || enviando || operacion?.incierta || falloSesion) return;
        peticionApertura?.abort();
        const peticion = new AbortController();
        peticionApertura = peticion;
        const { signal, liberar } = plazoPeticion(20000, peticion.signal);
        try {
            const chat = chats.get(id) || await buscarConversacion(item => item.id === id, signal);
            if (signal.aborted || enviando || operacion?.incierta) return;
            if (!chat) {
                el("estado-lista").textContent = "La conversación del aviso ya no está disponible.";
                return;
            }
            if (chat.archivada !== archivadas) {
                archivadas = chat.archivada;
                actualizarPestanas();
                vaciarBandeja();
                cargarBandeja();
            }
            abrirChat(chat);
        } catch (error) {
            if (!peticion.signal.aborted) el("estado-lista").textContent = fallo(error);
        } finally {
            liberar();
            if (peticionApertura === peticion) peticionApertura = null;
        }
    }

    async function enviarMensaje(evento) {
        evento.preventDefault();
        if (el("enviar").disabled) return;
        const destinatario = activo.otro.referencia;
        operacion ||= { destinatario, texto: texto.value, adjunto, clave: claveEnvio() };
        enviando = true;
        anunciar("");
        controles();
        try {
            await enviar(operacion, estadoEnvio);
        } catch (error) {
            operacion.incierta ||= error.resultadoIncierto === true;
            if (!operacion.incierta && error.estado === 410) operacion = null;
            const aviso = fallo(error);
            anunciar(operacion?.incierta ? aviso + " El resultado del envío es incierto. Reintenta la misma operación." : aviso, true);
            if (error.message === "cuota_agotada") guardarCuota(await pedir("/cuota").catch(() => ({ restantes: 0, limite: 50 })));
            return;
        } finally {
            estadoEnvio(null);
            enviando = false;
            controles();
        }
        if (falloSesion) return;
        limpiarCompositor();
        anunciar("Mensaje enviado");
        if (!activo.id) {
            const pendiente = activo;
            const chat = await buscarConversacion(item => item.otro?.referencia === destinatario).catch(() => null);
            if (activo === pendiente && chat) {
                if (chat.archivada !== archivadas) {
                    archivadas = chat.archivada;
                    actualizarPestanas();
                    vaciarBandeja();
                }
                chats.set(chat.id, chat);
                abrirChat(chat, true);
            }
        } else {
            cargarHistorial(false, true);
        }
        cargarBandeja(false, true);
    }

    function actualizarPestanas() {
        for (const pestaña of raiz.querySelectorAll("[data-bandeja]")) {
            pestaña.setAttribute("aria-pressed", String((pestaña.dataset.bandeja === "archivadas") === archivadas));
        }
    }

    async function cambiarArchivo() {
        if (!activo?.id || el("archivar").disabled) return;
        const chat = activo;
        archivando = true;
        controles();
        try {
            await pedir("/conversaciones/" + chat.id + "/archivo", { post: true, datos: { archivada: !chat.archivada } });
            if (activo === chat) volver();
            vaciarBandeja();
            cargarBandeja();
        } catch (error) {
            if (activo === chat) anunciar(fallo(error), true);
        } finally {
            archivando = false;
            controles();
        }
    }

    async function marcarLectura(automatica = false) {
        if (!activo?.id || marcando || falloSesion || (!automatica && el("leer").disabled)) return;
        const chat = activo;
        const pendientes = [...visibles.values()].filter(fila =>
            !fila.mensaje.enviado && !fila.mensaje.leido_utc && (!automatica || textoVisible(fila)));
        if (!pendientes.length) return;
        let confirmado = false;
        marcando = true;
        controles();
        try {
            for (const fila of pendientes) {
                const mensaje = fila.mensaje;
                if (activo !== chat) break;
                if (!mensaje.leido_utc && (!automatica || textoVisible(fila))) {
                    const datos = await pedir("/conversaciones/" + chat.id + "/mensajes/" + mensaje.id + "/lectura", {
                        post: true, plazo: 20000,
                    });
                    if (datos.leido) {
                        confirmado = true;
                        mensaje.leido_utc = true;
                        const actual = activo === chat && visibles.get(mensaje.id);
                        if (actual) {
                            actual.mensaje.leido_utc ||= true;
                            exposicion.unobserve(actual.texto);
                        }
                    }
                }
            }
        } catch (error) {
            if (activo === chat) anunciar(fallo(error), true);
        } finally {
            marcando = false;
            if (!automatica && activo === chat) {
                acciones.open = false;
                acciones.querySelector("summary").focus();
            }
            controles();
            if (confirmado) canal.invalidar(true);
            if (confirmado || activo !== chat) programarLectura();
        }
    }

    function abrirSelector(tipo) {
        selector = { tipo, cursor: null, elementos: new Map(), filtro: "" };
        el("selector-titulo").textContent = tipo === "personas" ? "Nueva conversación" : "Seleccionar de Biblioteca";
        el("filtro-selector").placeholder = tipo === "personas" ? "Nombre o área" : "Título o nombre de archivo";
        el("filtro-selector").value = "";
        opciones.replaceChildren();
        dialogo.showModal();
        cargarOpciones();
    }

    async function cargarOpciones(mas = false) {
        const estado = selector;
        peticionSelector?.abort();
        const peticion = new AbortController();
        peticionSelector = peticion;
        const personas = estado.tipo === "personas";
        const filtro = new URLSearchParams();
        if (!personas) {
            filtro.set("destinatario", activo.otro.referencia);
            filtro.set("buscar", estado.filtro);
        }
        if (mas && estado.cursor) filtro.set("despues", estado.cursor);
        el("estado-selector").textContent = "Cargando…";
        el("mas-opciones").disabled = true;
        try {
            const datos = personas ? await pedir("/destinatarios?" + filtro, { signal: peticion.signal }) :
                await buscarDocumentos(filtro, peticion.signal);
            if (peticion.signal.aborted) return;
            if (!mas) estado.elementos.clear();
            datos.elementos.forEach(item => estado.elementos.set(item.referencia, { ...item, descarga: datos.descarga }));
            estado.cursor = datos.siguiente;
            pintarOpciones();
        } catch (error) {
            if (!peticion.signal.aborted) el("estado-selector").textContent = fallo(error);
        } finally {
            if (peticionSelector === peticion) el("mas-opciones").disabled = false;
        }
    }

    function pintarOpciones() {
        const personas = selector.tipo === "personas";
        const termino = normalizar(selector.filtro);
        const frecuencias = personas ? contarPerfiles(selector.elementos.values()) : null;
        opciones.replaceChildren();
        for (const opcion of selector.elementos.values()) {
            if (!referencia(opcion.referencia) || (personas && !normalizar([opcion.nombre, opcion.area || ""].join(" ")).includes(termino))) continue;
            const item = crear("li");
            const elegir = boton("", "");
            const identidad = crear("span", "mensajeria-fila-texto");
            identidad.append(crear("strong", "", opcion.nombre), crear("small", "",
                personas ? perfilSecundario(opcion, frecuencias) : opcion.nombreArchivo));
            const avatar = personas ? crear("span", "mensajeria-avatar", iniciales(opcion.nombre)) : icono(opcion.nombreArchivo);
            if (personas) avatar.setAttribute("aria-hidden", "true");
            elegir.append(avatar, identidad);
            elegir.addEventListener("click", () => {
                dialogo.close();
                if (!personas) {
                    elegirAdjunto({
                        referencia: opcion.referencia, nombre: opcion.nombreArchivo,
                        soloVista: opcion.soloVista, descarga: opcion.descarga,
                        modalidad: opcion.descarga ? "visualizar_y_descargar" : "visualizar",
                    });
                    texto.focus();
                    return;
                }
                const existente = [...chats.values()].find(chat => chat.otro?.referencia === opcion.referencia);
                abrirChat(existente || { id: null, otro: opcion, archivada: false });
            });
            item.append(elegir);
            opciones.append(item);
        }
        el("estado-selector").textContent = opciones.children.length ? "" :
            selector.cursor ? "Sin coincidencias en esta página. Puedes cargar más." : "No se encontraron opciones disponibles.";
        el("mas-opciones").hidden = !selector.cursor;
    }

    el("nuevo").addEventListener("click", () => abrirSelector("personas"));
    el("biblioteca").addEventListener("click", () => abrirSelector("documentos"));
    el("buscar-selector").addEventListener("submit", evento => {
        evento.preventDefault();
        selector.filtro = el("filtro-selector").value.trim();
        if (selector.tipo === "personas") pintarOpciones();
        else {
            selector.cursor = null;
            selector.elementos.clear();
            opciones.replaceChildren();
            el("mas-opciones").hidden = true;
            cargarOpciones();
        }
    });
    el("mas-opciones").addEventListener("click", () => cargarOpciones(true));
    dialogo.addEventListener("close", () => {
        if (dialogo.open) return;
        peticionSelector?.abort();
        programarLectura();
    });
    el("buscar").addEventListener("input", pintarBandeja);
    for (const pestaña of raiz.querySelectorAll("[data-bandeja]")) {
        pestaña.addEventListener("click", () => {
            const destino = pestaña.dataset.bandeja === "archivadas";
            if (archivadas === destino) return;
            archivadas = destino;
            actualizarPestanas();
            vaciarBandeja();
            cargarBandeja();
        });
    }
    el("volver").addEventListener("click", () => volver());
    el("cerrar-chat").addEventListener("click", () => volver());
    document.querySelector('.sidebar-nav a[href="/inicio"]')?.addEventListener("click", evento => {
        if (evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey) return;
        if (enviando || (operacion?.incierta && !falloSesion)) {
            evento.preventDefault();
            anunciar(enviando ? "Espera a que termine el envío antes de salir." :
                "Reintenta o descarta el envío pendiente antes de salir.", true);
        } else if ((borradores.size || texto.value || adjunto) &&
            !window.confirm("Los borradores de esta página se perderán al volver a Inicio. ¿Quieres salir?")) {
            evento.preventDefault();
        }
    });
    el("mas-chats").addEventListener("click", () => {
        paginandoChats = cargarBandeja(true).finally(() => { paginandoChats = null; });
    });
    el("reintentar-lista").addEventListener("click", () => canal.invalidar(true));
    el("mas-mensajes").addEventListener("click", () => {
        paginandoMensajes = cargarHistorial(true).finally(() => { paginandoMensajes = null; });
    });
    el("reintentar-historial").addEventListener("click", () => cargarHistorial(false, true));
    el("archivar").addEventListener("click", cambiarArchivo);
    el("leer").addEventListener("click", () => marcarLectura());
    texto.addEventListener("input", () => { operacion = null; controles(); });
    el("adjuntar").addEventListener("click", () => el("archivo").click());
    el("archivo").addEventListener("change", () => {
        const archivo = el("archivo").files[0];
        el("archivo").value = "";
        if (!archivo) return;
        if (!archivo.size || archivo.size > LIMITE || !["pdf", "docx", "xlsx", "pptx", "txt", "png", "jpg", "jpeg"].includes(formato(archivo.name))) {
            anunciar("Elige un archivo de formato permitido, con contenido y de hasta 20 MiB.", true);
            return;
        }
        anunciar("");
        elegirAdjunto({ archivo });
    });
    el("compositor").addEventListener("submit", enviarMensaje);
    el("descartar").addEventListener("click", () => {
        operacion = null;
        anunciar("Reintento descartado. Consulta el historial antes de iniciar otro envío.", true);
        controles();
        if (activo?.id) cargarHistorial(false, true);
        cargarBandeja(false, true);
    });

    const canal = conectarMensajeria({
        ruta: campana.dataset.rutaWs,
        async actualizar(sincronizacion) {
            await paginandoChats;
            if (sincronizacion.signal.aborted) return false;
            if (!await cargarBandeja(false, true, sincronizacion)) return false;
            await paginandoMensajes;
            if (sincronizacion.signal.aborted) return false;
            return cargarHistorial(false, true, sincronizacion);
        },
        cerrarSesion(error) { anunciar(fallo(error, true), true); },
        informar(error) {
            el("estado-lista").textContent = mensajeError(error);
            el("reintentar-lista").hidden = false;
        },
    });
    document.addEventListener("siged:mensajeria-actualizar", () => canal.invalidar());
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && activo?.id) {
            for (const fila of visibles.values()) tarjetaPorComprobar(fila, activo.id);
            programarLectura();
        }
    });
    window.addEventListener("focus", programarLectura);
    window.visualViewport?.addEventListener("resize", programarLectura);
    campana.addEventListener("toggle", () => { if (campana.open) canal.invalidar(); });
    campana.addEventListener("click", evento => {
        const enlace = evento.target.closest("a[data-conversacion]");
        if (!enlace || evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey) return;
        evento.preventDefault();
        if (enviando || operacion?.incierta) return;
        campana.open = false;
        if (activo?.id === enlace.dataset.conversacion) el("chat-titulo").focus({ preventScroll: true });
        else campana.querySelector("summary").focus();
        abrirConversacionAviso(enlace.dataset.conversacion);
    });
    const idInicial = new URLSearchParams(location.search).get("conversacion");
    if (idInicial) abrirConversacionAviso(idInicial);
    function ajustarVista() {
        const menu = document.querySelector(".sidebar-menu");
        menu.open = !movil.matches;
        if (movil.matches && activo && document.activeElement?.closest(".mensajeria-bandeja")) el("chat-titulo").focus();
    }
    function ajustarTeclado() {
        const viewport = window.visualViewport;
        const altura = viewport?.scale === 1 && movil.matches ? Math.floor(viewport.height) : 0;
        if (altura) shell.style.setProperty("--mensajeria-viewport", altura + "px");
        else shell.style.removeProperty("--mensajeria-viewport");
        shell.toggleAttribute("data-mensajeria-compacta", altura > 0 && altura < 500);
    }
    movil.addEventListener("change", ajustarVista);
    window.visualViewport?.addEventListener("resize", ajustarTeclado);
    ajustarVista();
    ajustarTeclado();
}
