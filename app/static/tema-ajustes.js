(() => {
    const selector = document.getElementById("tema-ajustes");
    if (!selector) return;

    const aplicarTema = () => {
        const tema = selector.value;
        document.documentElement.dataset.tema = tema;
        document.querySelector('meta[name="color-scheme"]').content =
            {claro: "light", oscuro: "dark", automatico: "light dark"}[tema];
    };
    selector.addEventListener("change", aplicarTema);
    window.addEventListener("pageshow", aplicarTema);
})();
