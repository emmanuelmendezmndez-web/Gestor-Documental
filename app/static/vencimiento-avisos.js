(() => {
    for (const campo of document.querySelectorAll("[data-duracion-aviso]")) {
        const duracion = campo.querySelector("select");
        const personalizada = campo.querySelector("[data-dias-personalizados]");
        const dias = personalizada.querySelector("input");
        const actualizarCampo = () => {
            const activa = duracion.value === "personalizada";
            personalizada.hidden = !activa;
            dias.disabled = !activa;
            dias.required = activa;
        };
        duracion.addEventListener("change", actualizarCampo);
        window.addEventListener("pageshow", actualizarCampo);
        actualizarCampo();
    }

    const panel = document.querySelector("[data-avisos-vigentes]");
    if (!panel) return;
    const inicio = Date.now();
    const avisos = Array.from(panel.querySelectorAll("[data-segundos-vigente]"), tarjeta => ({
        tarjeta,
        vence: inicio + Number(tarjeta.dataset.segundosVigente) * 1000,
    }));
    if (!avisos.length) return;

    let temporizador;
    function actualizarAvisos() {
        window.clearTimeout(temporizador);
        const ahora = Date.now();
        let siguiente = Infinity;
        for (const { tarjeta, vence } of avisos) {
            if (vence <= ahora) tarjeta.remove();
            else siguiente = Math.min(siguiente, vence);
        }
        panel.querySelector("[data-avisos-vacios]").hidden = Boolean(panel.querySelector(".aviso-card"));
        if (Number.isFinite(siguiente)) {
            temporizador = window.setTimeout(actualizarAvisos, Math.min(siguiente - ahora, 2147483647));
        }
    }
    document.addEventListener("visibilitychange", actualizarAvisos);
    window.addEventListener("pageshow", actualizarAvisos);
    actualizarAvisos();
})();
