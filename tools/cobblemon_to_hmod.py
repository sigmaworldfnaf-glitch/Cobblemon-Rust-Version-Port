#!/usr/bin/env python3
"""Converte o jar do Cobblemon (Fabric 1.21.1) em pacotes .hmod do Horizon.

Uso:
  python tools/cobblemon_to_hmod.py --jar Cobblemon.jar --out dist
Gera em --out:
  cobblemon_assets.hmod    so assets (modelos, texturas, sons, lang)
  cobblemon_vanilla.hmod   assets + dados em formato vanilla (receitas, loot, tags...)
  cobblemon_full.hmod      assets + TODOS os dados do cobblemon (inclui species etc.)
  cobblemon_native_data.zip  dados proprios do Cobblemon + showdown.zip + licencas
                             (para o futuro mod nativo .hnmod ler)
  relatorio.txt            contagens, limites e arquivos descartados
Nada aqui e publicado: os arquivos so existem no seu computador/artefato.
"""
import argparse, hashlib, json, os, sys, zipfile, collections

ID = "cobblemon"
LIMIT_FILES, LIMIT_FILE, LIMIT_TOTAL = 65536, 16 * 1024 * 1024, 512 * 1024 * 1024
OK_EXT = {".json", ".png", ".ogg", ".nbt", ".mcmeta", ".txt"}
# dados do cobblemon que seguem formato vanilla do Minecraft
VANILLA_DIRS = {"recipe", "loot_table", "advancement", "tags", "structure",
                "worldgen", "painting_variant", "trim_pattern"}
SKIP_ASSET_DIRS = {"shaders"}            # GLSL do Minecraft nao serve no Horizon (Rust)
SKIP_NAMES = {"license", "separate_assets.py", "species.schema.json"}
EXTRA_NS = ("assets/minecraft/atlases/", "data/minecraft/tags/", "data/c/tags/")

TOML = f'''id = "{ID}"
name = "Cobblemon (port)"
version = "0.1.0"
description = "Port nao oficial: assets e dados do Cobblemon 1.8.4 para o Horizon"
authors = ["Cobblemon Team (original)"]
api = "0.2"
side = "both"
capabilities = ["registries"]
'''

def classify(name):
    """Retorna (destino, grupo) ou (None, motivo)."""
    p = name.split("/")
    base = p[-1]
    if name.endswith("/"):
        return None, "dir"
    if base in SKIP_NAMES:
        return None, "licenca/script"
    ext = os.path.splitext(base)[1].lower()
    if p[0] == "assets" and p[1] == ID:
        if len(p) > 3 and p[2] in SKIP_ASSET_DIRS:
            return None, "shaders"
        if ext not in OK_EXT:
            return None, "ext:" + ext
        return "assets", "assets"
    if name.startswith("assets/minecraft/atlases/") and ext == ".json":
        return "assets", "atlas_minecraft"
    if p[0] == "data" and p[1] == ID:
        if ext == ".molang":
            return "native", "molang"        # scripts Molang: so o mod nativo le
        if ext not in OK_EXT and name != "data/cobblemon/showdown.zip":
            return None, "ext:" + ext
        if name == "data/cobblemon/showdown.zip":
            return "native", "showdown"
        top = p[2] if len(p) > 3 else ""
        return ("vanilla" if top in VANILLA_DIRS else "custom"), top or "raiz"
    if name.startswith(("data/minecraft/tags/", "data/c/tags/")) and ext == ".json":
        return "vanilla", "tags_" + p[1]
    return None, "namespace_ignorado:" + (p[1] if len(p) > 1 else p[0])

def build(z, entries, path, include):
    n = tot = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as o:
        o.writestr("horizon-mod.toml", TOML)
        for name, dest in entries:
            if dest in include:
                data = z.read(name)
                o.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
                n += 1; tot += len(data)
    return n + 1, tot

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", required=True)
    ap.add_argument("--out", default="dist")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    z = zipfile.ZipFile(a.jar)
    entries, skipped, big = [], collections.Counter(), []
    for i in z.infolist():
        dest, grp = classify(i.filename)
        if dest is None:
            if grp != "dir": skipped[grp] += 1
            continue
        if i.file_size > LIMIT_FILE:
            big.append(i.filename); skipped["maior_que_16MiB"] += 1; continue
        entries.append((i.filename, dest))
    # licencas: uma copia por conteudo distinto
    lic = {}
    for n in z.namelist():
        if n.endswith("/license") or n == "LICENSE":
            h = hashlib.sha1(z.read(n)).hexdigest()
            lic.setdefault(h, []).append(n)
    profiles = {
        "assets":  {"assets"},
        "vanilla": {"assets", "vanilla"},
        "full":    {"assets", "vanilla", "custom"},
    }
    rep = ["RELATORIO DA CONVERSAO COBBLEMON -> HMOD", ""]
    for prof, inc in profiles.items():
        path = os.path.join(a.out, f"cobblemon_{prof}.hmod")
        n, tot = build(z, entries, path, inc)
        size = os.path.getsize(path)
        ok = n <= LIMIT_FILES and tot <= LIMIT_TOTAL
        rep.append(f"[{prof}] {n} arquivos, {tot/1e6:.1f} MB descompactado, "
                   f"{size/1e6:.1f} MB zip -> limites do Horizon: {'OK' if ok else 'ESTOUROU'}")
    # pacote para o mod nativo
    nat = os.path.join(a.out, "cobblemon_native_data.zip")
    with zipfile.ZipFile(nat, "w", zipfile.ZIP_DEFLATED) as o:
        for name, dest in entries:
            if dest in ("custom", "native"):
                o.writestr(name, z.read(name))
        for h, names in lic.items():
            o.writestr(f"licencas/{h[:8]}.txt", z.read(names[0]))
        o.writestr("licencas/INDICE.json", json.dumps(
            {h[:8]: names for h, names in lic.items()}, indent=1))
    rep += ["", f"native_data: {os.path.getsize(nat)/1e6:.1f} MB (dados proprios + showdown.zip + licencas)",
            "", "DESCARTADOS (motivo: quantidade):"]
    rep += [f"  {k}: {v}" for k, v in skipped.most_common()]
    if big: rep += ["", "Maiores que 16 MiB:"] + ["  " + b for b in big]
    rep += ["", "Contagem por grupo incluido:"]
    c = collections.Counter(); 
    for name, dest in entries: c[(dest, "/".join(name.split("/")[:3]))] += 1
    for (d, k), v in sorted(c.items(), key=lambda x: -x[1])[:25]: rep.append(f"  {v:6d} {d:8s} {k}")
    open(os.path.join(a.out, "relatorio.txt"), "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep))

if __name__ == "__main__":
    sys.exit(main())
