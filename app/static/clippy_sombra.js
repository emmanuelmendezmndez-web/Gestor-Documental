(() => {
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    if (!token) return;

    function observar(id) {
        const texto = document.getElementById(id)?.value.trim();
        if (!texto || texto.length > 300) return;
        void fetch("/asistente/sombra", {
            method: "POST",
            headers: {"Content-Type": "application/json", "X-CSRF-Token": token},
            body: JSON.stringify({texto}),
            keepalive: true,
        }).catch(() => {});
    }

    document.getElementById("abrir-busqueda-asistida")?.addEventListener(
        "click", () => observar("busqueda-global"), {capture: true});
    document.getElementById("proponer-contexto")?.addEventListener(
        "click", () => observar("instruccion-contextual"), {capture: true});
})();
