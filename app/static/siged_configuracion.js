(() => {
    const elemento = document.getElementById("siged-configuracion");
    if (!elemento) return;
    window.sigedOpcionesBusqueda = JSON.parse(elemento.dataset.opciones);
    window.sigedClippyConfig = JSON.parse(elemento.dataset.clippy);
})();
