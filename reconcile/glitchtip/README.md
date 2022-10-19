<font size=24> GlitchTip </font>
---

[toc]

# Introduction

This integration manages the following glitchtip objects:

* organizations
* teams
* projects
* and users


# Development

Development and testing were done for `glitchtip/glitchtip:v2.0.5`

glitchtip `docker-compose.yml` for local development:

```yaml
x-environment:
  &default-environment
  DATABASE_URL: postgres://postgres:postgres@postgres:5432/postgres
  SECRET_KEY: whatever
  DEBUG: "true"
  EMAIL_BACKEND: "django.core.mail.backends.console.EmailBackend"
  PORT: 8000
  GLITCHTIP_DOMAIN: http://localhost:8000
  CELERY_WORKER_CONCURRENCY: 1
x-depends_on:
  &default-depends_on
  - postgres
  - redis

services:
  postgres:
    image: postgres:13
    environment:
      POSTGRES_HOST_AUTH_METHOD: "trust"
    restart: unless-stopped
    volumes:
      - pg-data:/var/lib/postgresql/data
    networks:
      - qontract-development
  redis:
    image: redis
    restart: unless-stopped
    networks:
      - qontract-development
  glitchtip:
    image: glitchtip/glitchtip:v2.0.5
    depends_on: *default-depends_on
    ports:
      - "8000:8000"
    environment: *default-environment
    restart: unless-stopped
    networks:
      - qontract-development
  worker:
    image: glitchtip/glitchtip:v2.0.5
    command: ./bin/run-celery-with-beat.sh
    depends_on: *default-depends_on
    environment: *default-environment
    restart: unless-stopped
    networks:
      - qontract-development
  migrate:
    image: glitchtip/glitchtip:v2.0.5
    depends_on: *default-depends_on
    command: "./manage.py migrate"
    environment: *default-environment
    networks:
      - qontract-development

volumes:
  pg-data:


networks:
  qontract-development:
    external:
      name: qontract-development
```

# Fixtures

The unit tests use this structure and are based on these [app-interface-dev-data](https://gitlab.cee.redhat.com/app-sre/app-interface-dev-data/-/merge_requests/19) definitions.

```mermaid
classDiagram
    direction TB
    %% Instance & Orgs
    GlitchTipDev_Instance <-- ESA_Organization
    GlitchTipDev_Instance <-- NASA_Organization

    %% Projects
    NASA_Organization <-- apollo_11_flight_control_Project
    NASA_Organization <-- apollo_11_spacecraft_Project
    ESA_Organization <-- rosetta_flight_control_Project
    ESA_Organization <-- rosetta_spacecraft_Project

    %% Teams
    apollo_11_flight_control_Project <-- nasa_flight_control_Team
    apollo_11_flight_control_Project <-- nasa_pilots_Team
    apollo_11_spacecraft_Project <-- nasa_pilots_Team
    rosetta_flight_control_Project <-- esa_flight_control_Team
    rosetta_flight_control_Project <-- esa_pilots_Team
    rosetta_spacecraft_Project <-- esa_pilots_Team

    %% Users
    %% pilot
    ESA_Organization <-- SamanthaCristoforetti_User
    %% flight-control
    ESA_Organization <-- MatthiasMaurer_User
    ESA_Organization <-- TimPeake_User
    %% owner role in organizations;
    ESA_Organization <-- GlobalFlightDirector_User
    %% automation account, must be ignored
    ESA_Organization <-- sd_app_sre_glitchtip_User

    %% automation account, must be ignored
    NASA_Organization <-- sd_app_sre_glitchtip_User
    %% owner role in organizations; invited to nasa-flight-control but not accepted yet
    NASA_Organization <-- GlobalFlightDirector_User
    %% pilots
    NASA_Organization <-- NeilArmstrong_User
    %% user account not created yet, invited but user ignored the invitation
    NASA_Organization <-- BuzzAldrin_User
    %% ordinary user
    NASA_Organization <-- MichaelCollins_User

    %% Team memberships
    esa_pilots_Team <-- SamanthaCristoforetti_User
    esa_flight_control_Team <-- MatthiasMaurer_User
    esa_flight_control_Team <-- TimPeake_User
    esa_flight_control_Team <-- GlobalFlightDirector_User

    nasa_flight_control_Team <-- GlobalFlightDirector_User
    nasa_pilots_Team <-- NeilArmstrong_User
    nasa_pilots_Team <-- BuzzAldrin_User
    nasa_flight_control_Team <-- MichaelCollins_User
```

# Links

* [Design Doc](https://gitlab.cee.redhat.com/service/app-interface/-/blob/d12d7faa9d6136da69e4113ccbbed54781319173/docs/app-sre/design-docs/glitchtip.md)
* [GlitchTip App](https://visual-app-interface.devshift.net/services#/services/glitchtip/app.yml)
* [GlitchTip Stage Instance](https://glitchtip.stage.devshift.net/login)
