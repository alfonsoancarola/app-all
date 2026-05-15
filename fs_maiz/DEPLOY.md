# Deploy: app online para tus colegas

Arquitectura final (la más simple que encontramos):

```
Tu Mac (launchd, 2x/día)                  GitHub                Streamlit Cloud
    │                                       │                       │
    ▼                                       │                       ▼
    run_and_publish.sh                      │                   app.py
    ├─ correr_diario.py                     │                   (lee data/* del repo)
    │   ├─ baja SIO (Playwright local)      │                       ▲
    │   ├─ chequea MINAGRI                  │                       │
    │   └─ regenera matriz_*.csv            │                       │
    └─ git push data/* ─────────────────────┴───── auto-redeploy ───┘
                                       master
```

**Por qué este approach.** SIO Granos bloquea las IPs de GitHub Actions / Azure
(timeouts perpetuos). Tu Mac, con IP residencial argentina, no tiene ese
problema — y ya tiene Playwright + Chromium + el repo todo armado. Mover el
cron a otro lado sólo agregaría infra. Lo único que faltaba era que después de
correr el pipeline pushee los resultados al repo, y Streamlit Cloud sirve la
app a tus colegas con auth por whitelist.

**Limitación honesta.** Si tu Mac está apagado o sin red a las 10:00/17:00 ART,
ese día no se actualiza. La app sigue online con los últimos datos pusheados.
Si esto se vuelve un problema (vacaciones largas, etc.), migramos a VPS — pero
no antes de necesitarlo.

---

## Pasos para dejarlo andando

### 1. Habilitar el push automático en tu launchd

```bash
cd ~/fs_maiz

# Pull para tener los archivos nuevos (run_and_publish.sh, plist template, etc.)
git pull origin master

# Hacer ejecutable el wrapper (por si git no preservó el permiso)
chmod +x run_and_publish.sh

# Re-programar launchd para que use el wrapper en vez de python directo.
# Esto regenera el .plist apuntando a run_and_publish.sh y lo carga.
make schedule HORAS=10:00,17:00
```

`make schedule` lee el template `com.alfonso.fsmaiz.plist` (ya actualizado
para invocar el wrapper) y lo instala en `~/Library/LaunchAgents/`.

### 2. Asegurar que el SSH push funcione desde launchd

Esto es lo único que requiere atención: launchd a veces no hereda el
`ssh-agent` de tu sesión interactiva, así que la SSH key tiene que estar
accesible sin passphrase prompt.

```bash
# Verificar qué key usás para GitHub:
ssh -T git@github.com
# Debería decir: "Hi alfonsoancarola! You've successfully authenticated, ..."

# Si tu key tiene passphrase, guardala en el Keychain:
ssh-add --apple-use-keychain ~/.ssh/id_ed25519   # o id_rsa, lo que uses

# Configurar ~/.ssh/config para que SSH use el Keychain automáticamente:
cat >> ~/.ssh/config <<'EOF'

Host github.com
  AddKeysToAgent yes
  UseKeychain yes
  IdentityFile ~/.ssh/id_ed25519
EOF
```

Después de esto, launchd va a poder hacer `git push` sin intervención.

### 3. Probar el wrapper a mano antes de confiar en el cron

```bash
cd ~/fs_maiz
./run_and_publish.sh
```

Esto va a:
- Correr el pipeline (~3-5 min)
- Mostrarte logs en stdout con prefijo `[publish]`
- Si el pipeline OK y hay cambios → commit + push
- Si el pipeline falla → no pushea, exit con código != 0

Si funciona, dejá que launchd lo corra solo a las 10:00 y 17:00. Si querés
forzar un run inmediato:

```bash
launchctl start com.$(whoami).fsmaiz
tail -f launchd.log   # ver el output en vivo
```

### 4. Verificar que Streamlit Cloud detecte el push

Después de un push exitoso, andá al panel de tu app en
https://share.streamlit.io y deberías ver en el log un mensaje tipo
"Detected change in repository — rebooting app". Tarda ~30s en estar al aire
con los datos nuevos.

---

## Setup inicial de Streamlit Cloud (one-time)

Si todavía no conectaste el repo a Streamlit Cloud:

1. https://share.streamlit.io → entrá con la cuenta de GitHub `alfonsoancarola`.
2. **"Create app"** → **"Deploy a public app from GitHub"** (soporta repos privados igual).
3. Llená:
   - **Repository:** `alfonsoancarola/farmer-selling`
   - **Branch:** `master`
   - **Main file path:** `app.py`
   - **App URL:** ej. `fs-maiz` → te queda `fs-maiz.streamlit.app`
4. **Deploy.** Primer build: ~3-5 min.

### Secrets

⋯ → **Settings → Secrets**, pegá:

```toml
FS_MODO = "private"
```

### Whitelist de colegas

⋯ → **Settings → Sharing** → **"Only specific people"**. Agregá los emails:

- `alfonso.ancarola@gmail.com`
- (uno por línea, los emails de Google de tus colegas)

Cada colega entra a `https://fs-maiz.streamlit.app`, se loguea con Google, y si
su email está en la lista ve la app. Si no, 403.

---

## Validar que todo funciona

1. `./run_and_publish.sh` corrió en verde y hubo `git push` en los logs.
2. En `https://github.com/alfonsoancarola/farmer-selling/commits/master` ves un
   commit reciente del autor `fs-publisher` con mensaje "data: actualización
   automática …".
3. La app en `https://fs-maiz.streamlit.app` muestra los datos nuevos (mirá la
   fecha del último embarque MINAGRI en la sidebar — debería ser la del día).
4. Un colega no whitelisteado intenta entrar y recibe 403.

---

## Troubleshooting

**El wrapper falla con `Permission denied` al hacer `git push`.**
La SSH key no es accesible desde launchd. Repetí la sección 2 (Keychain). Para
debuggear: corré `./run_and_publish.sh` desde una terminal donde recién hiciste
login — si ahí funciona pero desde launchd no, es el agent/Keychain.

**El pipeline falla pero el cron sigue intentando 2x al día.**
Revisá `~/fs_maiz/launchd.log`. Si SIO mismo está caído, el wrapper hace exit
sin pushear (correcto — no querés pushear datos parciales). El día siguiente
re-intenta.

**Streamlit Cloud no detecta el push.**
A veces tarda. Forzá un reboot: ⋯ → **Reboot app**. Si el problema persiste,
chequeá que el commit haya llegado a `origin/master` (no a otra branch).

**Quiero pausar el cron temporalmente (ej. me voy de vacaciones).**

```bash
make unschedule        # desinstala el launchd
# … vuelve de vacaciones …
make schedule          # re-instala
```

---

## Costos

- **Streamlit Community Cloud:** gratis, repos privados, whitelist por email.
- **GitHub:** gratis, repo privado.
- **Tu Mac:** ya está prendido.

Total: $0/mes.

---

## El workflow de GitHub Actions

El archivo `.github/workflows/daily-cron.yml` quedó como `workflow_dispatch`
only (sin cron). Si en el futuro probás un fix para el bloqueo de SIO desde
GHA (proxy residencial, self-hosted runner, otro provider), podés
re-habilitarlo descomentando el bloque `schedule:`. Por ahora no se ejecuta
solo, así que no genera ruido.
