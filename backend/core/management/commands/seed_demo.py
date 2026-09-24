"""
Carga una base de demostración con datos 100% ficticios.

Pensado para la instancia pública de demo (portafolio): institución inventada,
personas inventadas, DNIs en el rango 99.xxx.xxx y emails @demo.invalid, así
que nada de lo que genera puede coincidir con una persona real.

Reutiliza los mismos servicios que usa la carga real (`_import_estudiante_record`,
`DocenteService`), de modo que la demo ejercita el mismo código que producción.

SEGURIDAD: solo corre con la variable de entorno DEMO_MODE=true. Con --reset
borra TODA la base antes de cargar; por eso nunca debe existir DEMO_MODE en
DEV ni en producción.

Uso:
    DEMO_MODE=true python manage.py seed_demo --reset --yes
"""

from __future__ import annotations

import io
import os
import random
from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.primera_carga.services.importacion import _import_estudiante_record
from core.models import (
    Comision,
    Docente,
    Estudiante,
    InscripcionMateriaEstudiante,
    InscripcionMesa,
    Materia,
    MesaExamen,
    Persona,
    PlanDeEstudio,
    Profesorado,
    Regularidad,
    StaffAsignacion,
    Turno,
    UserProfile,
)

DEMO_PASSWORD = "demo1234"
EMAIL_DOMAIN = "demo.invalid"  # dominio reservado: nunca entrega correo real

NOMBRES_F = [
    "Sofía", "Valentina", "Martina", "Camila", "Lucía", "Julieta", "Florencia", "Agustina",
    "Micaela", "Rocío", "Milagros", "Abril", "Candela", "Paula", "Carolina", "Natalia",
    "Belén", "Antonella", "Daiana", "Aylén", "Brenda", "Celeste", "Jazmín", "Lorena",
]
NOMBRES_M = [
    "Mateo", "Santiago", "Benjamín", "Joaquín", "Tomás", "Lautaro", "Facundo", "Agustín",
    "Nicolás", "Franco", "Gonzalo", "Matías", "Ezequiel", "Bruno", "Leandro", "Iván",
    "Emiliano", "Thiago", "Maximiliano", "Julián", "Ramiro", "Federico", "Marcos", "Diego",
]
APELLIDOS = [
    "González", "Rodríguez", "Gómez", "Fernández", "López", "Díaz", "Martínez", "Pérez",
    "García", "Sánchez", "Romero", "Sosa", "Álvarez", "Torres", "Ruiz", "Ramírez", "Flores",
    "Acosta", "Benítez", "Medina", "Herrera", "Suárez", "Aguirre", "Giménez", "Gutiérrez",
    "Pereyra", "Rojas", "Molina", "Castro", "Ortiz", "Silva", "Núñez", "Luna", "Juárez",
    "Cabrera", "Ríos", "Morales", "Godoy", "Moreno", "Ferreyra", "Domínguez", "Carrizo",
]
CALLES = ["San Martín", "Belgrano", "Rivadavia", "Moyano", "Perito Moreno", "Islas Malvinas",
          "Thorne", "Estrada", "Santa Fe", "Lasserre", "Piedrabuena", "El Cano"]

# Carreras ficticias: (nombre, duración, [materias por año])
CARRERAS = [
    (
        "Profesorado de Educación Primaria",
        4,
        [
            ["Pedagogía", "Didáctica General", "Psicología Educacional", "Lectura y Escritura Académica",
             "Práctica Docente I"],
            ["Didáctica de la Matemática I", "Didáctica de la Lengua I", "Sujetos de la Educación Primaria",
             "Historia de la Educación Argentina", "Práctica Docente II"],
            ["Didáctica de la Matemática II", "Didáctica de las Ciencias Naturales",
             "Didáctica de las Ciencias Sociales", "Educación Sexual Integral", "Práctica Docente III"],
            ["Ética y Construcción Ciudadana", "Alfabetización Inicial", "TIC en la Enseñanza",
             "Residencia Pedagógica"],
        ],
    ),
    (
        "Profesorado de Educación Secundaria en Matemática",
        4,
        [
            ["Álgebra I", "Análisis Matemático I", "Geometría I", "Pedagogía", "Práctica Docente I"],
            ["Álgebra II", "Análisis Matemático II", "Geometría II", "Didáctica General",
             "Práctica Docente II"],
            ["Probabilidad y Estadística", "Análisis Matemático III", "Didáctica de la Matemática",
             "Práctica Docente III"],
            ["Historia de la Matemática", "Modelización Matemática", "Residencia Docente"],
        ],
    ),
    (
        "Tecnicatura Superior en Desarrollo de Software",
        3,
        [
            ["Programación I", "Bases de Datos I", "Matemática Discreta", "Sistemas Operativos",
             "Inglés Técnico I"],
            ["Programación II", "Bases de Datos II", "Desarrollo Web", "Ingeniería de Software",
             "Inglés Técnico II"],
            ["Desarrollo de Aplicaciones Móviles", "Seguridad Informática", "Proyecto Final Integrador",
             "Práctica Profesionalizante"],
        ],
    ),
]

# Cuentas de acceso público de la demo (se muestran en la pantalla de login).
CUENTAS_STAFF = [
    # (dni/usuario, nombre, apellido, grupo, superusuario)
    ("99000001", "Admin", "Demo", None, True),
    ("99000002", "Silvia", "Secretaría", "secretaria", False),
    ("99000003", "Bernardo", "Bedelía", "bedel", False),
    ("99000004", "Carla", "Coordinación", "coordinador", False),
]


class Command(BaseCommand):
    help = "Carga datos 100% ficticios para la instancia de demostración (requiere DEMO_MODE=true)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Borra TODA la base antes de cargar.")
        parser.add_argument("--yes", action="store_true", help="No pedir confirmación.")
        parser.add_argument("--estudiantes", type=int, default=180, help="Cantidad de estudiantes (180).")
        parser.add_argument("--seed", type=int, default=2026, help="Semilla aleatoria (resultados repetibles).")

    def handle(self, *args, reset: bool, yes: bool, estudiantes: int, seed: int, **options):
        if os.getenv("DEMO_MODE", "").lower() != "true":
            raise CommandError(
                "Este comando solo corre en la instancia DEMO (variable de entorno DEMO_MODE=true). "
                "Nunca definas DEMO_MODE en DEV ni en producción."
            )
        if reset and not yes:
            answer = input("Se va a BORRAR TODA la base de datos de esta instancia. Escribí 'demo' para seguir: ")
            if answer.strip().lower() != "demo":
                raise CommandError("Cancelado.")

        if reset:
            self.stdout.write("Vaciando la base...")
            call_command("flush", interactive=False, verbosity=0)

        self.rng = random.Random(seed)
        self.hoy = date.today()
        self.anio = self.hoy.year
        self._dni_seq = 99100000

        call_command("setup_horarios", stdout=io.StringIO())

        with transaction.atomic():
            carreras = self._crear_carreras()
            docentes = self._crear_docentes(28)
            self._crear_staff(carreras)
            comisiones = self._crear_comisiones(carreras, docentes)
            alumnos = self._crear_estudiantes(carreras, estudiantes)
            stats = self._crear_trayectorias(alumnos, comisiones, docentes)

        self.stdout.write(self.style.SUCCESS("\nDemo cargada."))
        self.stdout.write(
            f"Carreras: {len(carreras)} | Materias: {Materia.objects.count()} | Docentes: {len(docentes)} | "
            f"Estudiantes: {len(alumnos)}"
        )
        self.stdout.write(
            f"Inscripciones {self.anio}: {stats['inscripciones']} | Regularidades: {stats['regularidades']} | "
            f"Finales rendidos: {stats['finales']}"
        )
        self.stdout.write("\nCuentas de acceso (contraseña para todas: %s):" % DEMO_PASSWORD)
        for dni, nombre, apellido, grupo, su in CUENTAS_STAFF:
            self.stdout.write(f"  {dni}  {'admin' if su else grupo:<12} {nombre} {apellido}")
        self.stdout.write(f"  {docentes[0].dni}  docente      {docentes[0].nombre} {docentes[0].apellido}")
        self.stdout.write(f"  {alumnos[0].dni}  estudiante   {alumnos[0].nombre} {alumnos[0].apellido}")

    # ------------------------------------------------------------------ helpers

    def _nuevo_dni(self) -> str:
        self._dni_seq += self.rng.randint(1, 37)
        return str(self._dni_seq)

    def _persona_ficticia(self, dni: str | None = None, nombre: str | None = None, apellido: str | None = None):
        genero = self.rng.choice(["F", "M"])
        nombre = nombre or self.rng.choice(NOMBRES_F if genero == "F" else NOMBRES_M)
        apellido = apellido or self.rng.choice(APELLIDOS)
        dni = dni or self._nuevo_dni()
        return {
            "dni": dni,
            "nombre": nombre,
            "apellido": apellido,
            "email": f"{_slug(nombre)}.{_slug(apellido)}.{dni[-4:]}@{EMAIL_DOMAIN}",
            "telefono": f"2964 000{self.rng.randint(100, 999)}",
            "domicilio": f"{self.rng.choice(CALLES)} {self.rng.randint(100, 2999)}",
            "genero": genero,
            "cuil": f"{'27' if genero == 'F' else '20'}-{dni}-{self.rng.randint(0, 9)}",
            "fecha_nacimiento": date(self.anio - self.rng.randint(19, 38), self.rng.randint(1, 12),
                                     self.rng.randint(1, 28)),
        }

    def _usuario_con_persona(self, datos: dict) -> tuple[User, Persona]:
        persona, _ = Persona.objects.update_or_create(dni=datos["dni"], defaults={
            k: v for k, v in datos.items() if k != "dni"
        })
        user = User.objects.filter(username=datos["dni"]).first() or User.objects.create_user(
            username=datos["dni"], password=DEMO_PASSWORD
        )
        UserProfile.objects.update_or_create(user=user, defaults={"persona": persona, "must_change_password": False})
        return user, persona

    # ------------------------------------------------------------------ carga

    def _crear_carreras(self) -> list[tuple[Profesorado, list[list[Materia]]]]:
        formatos = [Materia.FormatoMateria.ASIGNATURA] * 3 + [Materia.FormatoMateria.TALLER,
                                                              Materia.FormatoMateria.SEMINARIO]
        resultado = []
        for nombre, duracion, anios in CARRERAS:
            prof, _ = Profesorado.objects.get_or_create(
                nombre=nombre, defaults={"duracion_anios": duracion, "activo": True, "inscripcion_abierta": True}
            )
            plan, _ = PlanDeEstudio.objects.get_or_create(
                profesorado=prof, resolucion=f"Res. DEMO {100 + len(resultado)}/2022",
                defaults={"anio_inicio": 2022, "vigente": True},
            )
            por_anio = []
            for idx, materias in enumerate(anios, start=1):
                fila = []
                for nombre_materia in materias:
                    es_practica = "Práctica" in nombre_materia or "Residencia" in nombre_materia
                    materia, _ = Materia.objects.get_or_create(
                        plan_de_estudio=plan, nombre=nombre_materia, anio_cursada=idx,
                        defaults={
                            "formato": Materia.FormatoMateria.PRACTICA if es_practica else self.rng.choice(formatos),
                            "regimen": Materia.TipoCursada.ANUAL if es_practica else self.rng.choice(
                                [Materia.TipoCursada.ANUAL, Materia.TipoCursada.PRIMER_CUATRIMESTRE,
                                 Materia.TipoCursada.SEGUNDO_CUATRIMESTRE]),
                            "horas_semana": self.rng.choice([3, 4, 4, 5, 6]),
                        },
                    )
                    fila.append(materia)
                por_anio.append(fila)
            resultado.append((prof, por_anio))
        return resultado

    def _crear_docentes(self, cantidad: int) -> list[Docente]:
        grupo, _ = Group.objects.get_or_create(name="docente")
        docentes = []
        for _i in range(cantidad):
            datos = self._persona_ficticia()
            user, persona = self._usuario_con_persona(datos)
            user.groups.add(grupo)
            docente, _ = Docente.objects.get_or_create(persona=persona)
            docentes.append(docente)
        return docentes

    def _crear_staff(self, carreras) -> None:
        for dni, nombre, apellido, grupo_nombre, superusuario in CUENTAS_STAFF:
            datos = self._persona_ficticia(dni=dni, nombre=nombre, apellido=apellido)
            user, _persona = self._usuario_con_persona(datos)
            if superusuario:
                user.is_superuser = True
                user.is_staff = True
                user.save()
            if grupo_nombre:
                grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
                user.groups.add(grupo)
            if grupo_nombre in ("bedel", "coordinador"):
                for prof, _ in carreras:
                    StaffAsignacion.objects.get_or_create(
                        user=user, profesorado=prof, rol=grupo_nombre,
                        defaults={"turno": StaffAsignacion.Turno.VESPERTINO if grupo_nombre == "bedel" else None},
                    )

    def _crear_comisiones(self, carreras, docentes) -> dict[int, Comision]:
        turnos = list(Turno.objects.all()) or [Turno.objects.create(nombre="Turno Vespertino")]
        comisiones = {}
        for prof, por_anio in carreras:
            for fila in por_anio:
                for materia in fila:
                    comision, _ = Comision.objects.get_or_create(
                        materia=materia, anio_lectivo=self.anio, codigo="A",
                        defaults={"turno": self.rng.choice(turnos), "docente": self.rng.choice(docentes)},
                    )
                    comisiones[materia.id] = comision
        return comisiones

    def _crear_estudiantes(self, carreras, cantidad: int) -> list[Estudiante]:
        grupo, _ = Group.objects.get_or_create(name="estudiante")
        alumnos = []
        for i in range(cantidad):
            prof, por_anio = carreras[i % len(carreras)]
            # cohortes recientes con más ingresantes que las antiguas (deserción realista)
            anio_ingreso = self.anio - self.rng.choices(range(len(por_anio)), weights=[5, 4, 3, 2][: len(por_anio)])[0]
            datos = self._persona_ficticia()
            record = {
                **datos,
                "password_plane": DEMO_PASSWORD,
                "must_change_password": "false",
                "is_active": "true",
                "estado_legajo": self.rng.choices(["COMPLETO", "INCOMPLETO"], weights=[7, 3])[0],
                "anio_ingreso": str(anio_ingreso),
                "cohorte": str(anio_ingreso),
                "legajo": f"D-{anio_ingreso}-{i + 1:04d}",
            }
            estudiante, _ = _import_estudiante_record(record, profesorado=prof, estudiante_group=grupo)
            estudiante._demo_carrera = (prof, por_anio, anio_ingreso)
            alumnos.append(estudiante)
        return alumnos

    def _crear_trayectorias(self, alumnos, comisiones, docentes) -> dict:
        """Regularidades y finales de años anteriores + inscripciones del año en curso."""
        stats = {"inscripciones": 0, "regularidades": 0, "finales": 0}
        mesas: dict[tuple[int, int], MesaExamen] = {}

        for est in alumnos:
            prof, por_anio, anio_ingreso = est._demo_carrera
            anio_actual_carrera = min(self.anio - anio_ingreso + 1, len(por_anio))
            constancia = self.rng.random()  # algunos estudiantes van al día, otros se atrasan

            for anio_carrera in range(1, anio_actual_carrera + 1):
                ciclo = anio_ingreso + anio_carrera - 1
                for materia in por_anio[anio_carrera - 1]:
                    if ciclo == self.anio:
                        InscripcionMateriaEstudiante.objects.get_or_create(
                            estudiante=est, materia=materia, anio=ciclo,
                            defaults={"comision": comisiones.get(materia.id)},
                        )
                        stats["inscripciones"] += 1
                        continue

                    if self.rng.random() > 0.35 + constancia * 0.6:
                        situacion = self.rng.choice([Regularidad.Situacion.LIBRE_I,
                                                     Regularidad.Situacion.DESAPROBADO_PA])
                        nota_cursada = self.rng.randint(2, 5)
                    elif self.rng.random() < 0.25:
                        situacion, nota_cursada = Regularidad.Situacion.PROMOCIONADO, self.rng.randint(8, 10)
                    else:
                        situacion, nota_cursada = Regularidad.Situacion.REGULAR, self.rng.randint(6, 9)

                    Regularidad.objects.get_or_create(
                        estudiante=est, materia=materia, fecha_cierre=date(ciclo, 11, 28),
                        defaults={"situacion": situacion, "nota_final_cursada": nota_cursada},
                    )
                    stats["regularidades"] += 1

                    if situacion == Regularidad.Situacion.REGULAR and self.rng.random() < 0.3 + constancia * 0.6:
                        mesa = mesas.get((materia.id, ciclo))
                        if mesa is None:
                            mesa = MesaExamen.objects.create(
                                materia=materia, tipo=MesaExamen.Tipo.FINAL, fecha=date(ciclo, 12, 12),
                                aula=f"Aula {self.rng.randint(1, 12)}", cupo=40,
                                docente_presidente=self.rng.choice(docentes),
                            )
                            mesas[(materia.id, ciclo)] = mesa
                        nota = self.rng.choices([self.rng.randint(6, 10), self.rng.randint(2, 5)], weights=[8, 2])[0]
                        InscripcionMesa.objects.get_or_create(
                            mesa=mesa, estudiante=est,
                            defaults={
                                "fecha_resultado": mesa.fecha,
                                "condicion": InscripcionMesa.Condicion.APROBADO if nota >= 6
                                else InscripcionMesa.Condicion.DESAPROBADO,
                                "nota": nota,
                                "folio": str(self.rng.randint(1, 300)),
                                "libro": "D1",
                            },
                        )
                        stats["finales"] += 1

        # Mesas del próximo turno de examen, para que la agenda no esté vacía.
        proximo = self.hoy + timedelta(days=30)
        for (materia_id, _ciclo), mesa in list(mesas.items())[:20]:
            MesaExamen.objects.get_or_create(
                materia_id=materia_id, tipo=MesaExamen.Tipo.FINAL, fecha=proximo,
                defaults={"aula": mesa.aula, "cupo": 40, "docente_presidente": mesa.docente_presidente},
            )
        return stats


def _slug(texto: str) -> str:
    import unicodedata

    base = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "".join(ch for ch in base.lower() if ch.isalnum())
