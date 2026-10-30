
from locust import HttpUser, task, between
from locust.exception import StopUser
import os
import random
from app.catalogos import CATEGORIAS


class UsuarioGestor(HttpUser):
    # Pausa entre acciones de cada usuario
    wait_time = between(1, 3)

    # Datos de prueba. Puedes agregar valores que existan
    # realmente en tu biblioteca.
    terminos = [
        "oficio",
        "contrato",
        "informe",
        "acta",
        "documento",
    ]

    categorias = CATEGORIAS

    def on_start(self):
        usuario = os.environ.get("SIGED_LOCUST_USUARIO")
        password = os.environ.get("SIGED_LOCUST_PASSWORD")
        if not usuario or not password:
            raise StopUser("Configura SIGED_LOCUST_USUARIO y SIGED_LOCUST_PASSWORD para la instancia de prueba.")
        with self.client.post("/login", data={"usuario": usuario, "password": password},
                              allow_redirects=False, catch_response=True, name="Inicio de sesión") as respuesta:
            if respuesta.status_code != 303 or respuesta.headers.get("location") != "/inicio":
                respuesta.failure("No se pudo iniciar sesión en la instancia de prueba")
                raise StopUser()

    @task(5)
    def buscar_por_texto(self):
        termino = random.choice(self.terminos)

        self.client.get(
            "/",
            params={"buscar": termino},
            name="Búsqueda por texto",
        )

    @task(3)
    def filtrar_categoria(self):
        categoria = random.choice(self.categorias)

        self.client.get(
            "/",
            params={"categoria": categoria},
            name="Filtro por categoría",
        )

    @task(2)
    def busqueda_avanzada(self):
        parametros = {
            "buscar": random.choice(self.terminos),
            "oficio": random.choice(["", "123/2026", "45/2025"]),
            "departamento": "",
            "autor": random.choice(["", "Juan", "María"]),
            "desde": "",
            "hasta": "",
            "orden": "",
        }

        self.client.get(
            "/",
            params=parametros,
            name="Búsqueda avanzada",
        )

    @task(1)
    def abrir_biblioteca(self):
        self.client.get(
            "/",
            name="Biblioteca sin filtros",
        )
