"""
_gen_plist.py — Genera el .plist de launchd con uno o varios horarios.

Uso:
    python3 _gen_plist.py <here> <label> <horas_csv> <template_in> <plist_out>

Ejemplo:
    python3 _gen_plist.py "$HOME/fs_maiz" "com.alfonso.fsmaiz" "10:00,17:00" \
        com.alfonso.fsmaiz.plist ~/Library/LaunchAgents/com.alfonso.fsmaiz.plist
"""
import sys


def main():
    if len(sys.argv) != 6:
        print("uso: _gen_plist.py <here> <label> <horas_csv> <template_in> <plist_out>")
        sys.exit(2)

    here, label, horas_csv, template_in, plist_out = sys.argv[1:]
    horas = [h.strip() for h in horas_csv.split(",") if h.strip()]

    def _dict_for(h):
        hh, mm = h.split(":")
        return (
            "        <dict>\n"
            f"            <key>Hour</key>\n"
            f"            <integer>{int(hh)}</integer>\n"
            f"            <key>Minute</key>\n"
            f"            <integer>{int(mm)}</integer>\n"
            "        </dict>"
        )

    if len(horas) == 1:
        intervals = _dict_for(horas[0]).strip()
    else:
        body = "\n".join(_dict_for(h) for h in horas)
        intervals = "<array>\n" + body + "\n    </array>"

    with open(template_in, encoding="utf-8") as f:
        template = f.read()
    result = (template
              .replace("{{HERE}}", here)
              .replace("{{LABEL}}", label)
              .replace("{{INTERVALS}}", intervals))
    with open(plist_out, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"plist generado para {len(horas)} horario(s): {', '.join(horas)}")


if __name__ == "__main__":
    main()
