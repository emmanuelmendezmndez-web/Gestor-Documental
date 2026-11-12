(() => {
    const control = document.getElementById("login-visibilidad");
    const contrasena = document.getElementById("password");
    if (!control || !contrasena) return;

    control.addEventListener("click", () => {
        const mostrar = contrasena.type === "password";
        contrasena.type = mostrar ? "text" : "password";
        control.setAttribute("aria-pressed", String(mostrar));
    });
    control.hidden = false;
})();
