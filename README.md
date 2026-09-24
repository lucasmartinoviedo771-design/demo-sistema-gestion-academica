# Sistema de Gestión Académica — Demo

Plataforma web para institutos de educación superior: preinscripciones, legajos,
cursadas, regularidades, mesas de examen, actas en PDF y analítica institucional.

**Demo en vivo: https://demo.lucasoviedodev.org**
Datos 100% ficticios. En la pantalla de ingreso elegí un perfil (Administrador,
Secretaría, Bedelía, Coordinación, Docente o Estudiante) y tocá *Ingresar*.
La demo se reinicia todas las noches.

> Este repositorio es la versión pública de demostración de un sistema que está
> en producción en instituciones educativas reales. La institución que aparece
> ("Instituto Superior Demo") y todas las personas son inventadas.

---

## Qué resuelve

| Área | Funcionalidades |
|---|---|
| **Admisión** | Preinscripción online por etapas, checklist de documentación, formalización de inscripción, curso introductorio |
| **Legajo del estudiante** | Datos personales, documentación presentada, estado de legajo (completo / condicional), foto de perfil |
| **Trayectoria académica** | Inscripción a materias por comisión, regularidades, promociones, correlatividades, equivalencias |
| **Exámenes** | Mesas ordinarias / extraordinarias / especiales, inscripción, actas de examen y actas orales en PDF |
| **Docentes y cátedras** | Asignación de comisiones, horarios por turno, planillas de regularidad, asistencia |
| **Gestión institucional** | Roles (admin, secretaría, bedelía, coordinación, docente, estudiante), mensajería interna, títulos, alertas del sistema |
| **Analítica** | Panel de control con preinscripciones, alerta temprana de estudiantes en riesgo, rendimiento académico y evolución temporal |

## Stack

- **Backend:** Python 3.11, Django 5, Django Ninja (API REST), MySQL 8, Redis
- **Frontend:** React 18, TypeScript, Vite, Material UI, TanStack Query
- **Infraestructura:** Docker Compose, Nginx, Gunicorn, Cloudflare Tunnel
- **PDF:** WeasyPrint y ReportLab (actas, constancias, certificados)

## Seguridad

- Autenticación JWT en cookies `HttpOnly`, con revocación de tokens y *rate limiting* en el login
- Control de acceso por roles y por carrera (un bedel solo ve las carreras que tiene asignadas)
- Política CSP estricta, validación profunda de archivos subidos, auditoría de acciones sensibles
- Caché del cliente aislado por usuario: se limpia en login, logout y simulación de usuario
- Configuración 100% por variables de entorno; ningún secreto en el código

## Correr la demo localmente

Requisitos: Docker y Docker Compose.

```bash
cd backend
cp .env.example .env.demo   # completar SECRET_KEY, DB_PASSWORD y DB_ROOT_PASSWORD
docker compose -f docker-compose.demo.yml --env-file .env.demo up -d --build
docker compose -f docker-compose.demo.yml --env-file .env.demo exec backend \
    /app/.venv/bin/python manage.py migrate
docker compose -f docker-compose.demo.yml --env-file .env.demo exec backend \
    /app/.venv/bin/python manage.py seed_demo --reset --yes
```

Abrí http://localhost:8095 y usá cualquiera de los perfiles de prueba
(contraseña `demo1234`).

`seed_demo` genera 3 carreras, 50 materias, 28 docentes y 180 estudiantes con
inscripciones, regularidades y finales. Solo corre con `DEMO_MODE=true`, así que
no puede ejecutarse por error sobre una base real.

## Estructura

```
backend/
  apps/        módulos de negocio (estudiantes, docentes, preinscripciones, métricas…)
  core/        modelos, permisos, autenticación y comandos de gestión
  config/      settings y URLs de Django
frontend/
  src/pages/   pantallas por rol
  src/api/     cliente HTTP tipado
scripts/demo/  herramientas de la instancia de demostración
```

---

## English summary

Academic management platform for higher-education institutes (admissions,
student records, enrollments, exams, PDF records and analytics), built with
Django + React/TypeScript and deployed with Docker. **Live demo:**
https://demo.lucasoviedodev.org (fictitious data, one-click demo profiles).

## Autor

**Lucas Oviedo** — Desarrollador full stack (Python/Django + React)
Río Grande, Tierra del Fuego, Argentina
📧 lucasoviedodev@gmail.com

¿Necesitás un sistema de gestión a medida para tu institución u organización?
Escribime.
