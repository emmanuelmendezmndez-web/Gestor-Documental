(() => {
    const indicador = document.getElementById("estado-sistema");
    if (!indicador) return;

    const titulos = new Map([
        ["operativo", "Operativo"],
        ["degradado", "Funcionamiento degradado"],
        ["critico", "Estado crítico"],
    ]);
    const titulo = indicador.querySelector("[data-estado-titulo]");
    const lista = indicador.querySelector("[data-estado-incidencias]");
    let ultimaVista;
    let temporizador;
    let consultando = false;
    let sesionVigente = true;

    function mostrar(estado, incidencias) {
        const vista = JSON.stringify([estado, incidencias]);
        if (vista === ultimaVista) return;
        ultimaVista = vista;
        indicador.dataset.estado = estado;
        titulo.textContent = titulos.get(estado);
        lista.replaceChildren(...incidencias.map(texto => {
            const item = document.createElement("li");
            item.textContent = texto;
            return item;
        }));
    }

    async function consultar() {
        temporizador = undefined;
        if (document.hidden || consultando || !sesionVigente) return;
        consultando = true;
        const control = new AbortController();
        const limite = setTimeout(() => control.abort(), 8000);
        try {
            const respuesta = await fetch(indicador.dataset.url, {
                credentials: "same-origin", cache: "no-store", signal: control.signal,
            });
            if (respuesta.status === 401 || respuesta.status === 403) {
                sesionVigente = false;
                mostrar("degradado", ["La sesión ya no permite consultar el estado del sistema."]);
                return;
            }
            if (!respuesta.ok) throw new Error("Estado no disponible");
            const { estado, incidencias } = await respuesta.json();
            if (!titulos.has(estado) || !Array.isArray(incidencias)) throw new Error("Estado no disponible");
            mostrar(estado, incidencias);
        } catch {
            mostrar("degradado", ["No se pudo consultar el estado del sistema."]);
        } finally {
            clearTimeout(limite);
            consultando = false;
            if (sesionVigente) temporizador = setTimeout(consultar, 60000);
        }
    }

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && temporizador === undefined) consultar();
    });
    consultar();
})();
