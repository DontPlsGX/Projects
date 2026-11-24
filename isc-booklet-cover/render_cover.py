"""Render the ISC booklet cover artwork (Earth over Southeast Asia, lit, with
partner-university connection arcs) in the club palette.

    python3 render_cover.py [scale]      # scale 1.0 = A4 landscape @ 300 dpi

Needs: numpy, scipy, pillow, global-land-mask; cities.json (npm) for city lights.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get("ISC_CACHE", "/tmp/claude-0/isc_cache")
CITIES = os.environ.get("ISC_CITIES", "/tmp/claude-0/data/package/cities.json")
FONTS = os.environ.get("ISC_FONTS", "/tmp/claude-0/fonts")
os.makedirs(CACHE, exist_ok=True)

SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
W, H = int(3508 * SCALE), int(2480 * SCALE)
rng = np.random.default_rng(7)


def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


# ---- club palette ----------------------------------------------------------
NAVY_0 = hexc("#040B1E")
NAVY_1 = hexc("#0A1F4A")
NAVY_2 = hexc("#0F3A78")
BLUE_3 = hexc("#1B66B8")
BLUE_4 = hexc("#3A8EE6")
BLUE_5 = hexc("#9CC8F2")
CREAM = hexc("#FFF3E0")
PEACH = hexc("#FDE0B5")
SAND = hexc("#F2CC92")
GOLD = hexc("#D8AF72")
GOLD_D = hexc("#A97C38")
BRONZE = hexc("#6E4C22")
ORANGE = hexc("#EE8A3C")
ORANGE_D = hexc("#E06A20")


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    t = np.asarray(t, np.float32)[..., None] if np.ndim(t) else t
    return a * (1 - t) + b * t


def ramp(t, stops):
    """Piecewise-linear colour ramp. stops = [(pos, rgb), ...]."""
    t = np.clip(t, 0, 1)
    out = np.zeros(t.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(t, [s[0] for s in stops], [s[1][c] for s in stops])
    return out


def fbm_wrap(shape, *a, **k):
    """fbm that tiles seamlessly in x (longitude)."""
    h, w = shape
    pad = w // 4
    n = fbm((h, w + pad), *a, **k)
    t = np.linspace(0, 1, pad, dtype=np.float32)[None, :]
    out = n[:, :w].copy()
    out[:, :pad] = n[:, :pad] * t + n[:, w:] * (1 - t)
    return out


def fbm(shape, octaves=6, base=4, seed=0, persistence=0.55):
    """Fractal value noise in [0,1] on an image grid."""
    r = np.random.default_rng(seed)
    acc = np.zeros(shape, np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        g = r.random((max(2, int(n * shape[0] / max(shape))) + 1, n + 1)).astype(np.float32)
        layer = ndimage.zoom(g, (shape[0] / g.shape[0], shape[1] / g.shape[1]), order=3)
        acc += amp * layer[: shape[0], : shape[1]]
        tot += amp
        amp *= persistence
    acc /= tot
    return (acc - acc.min()) / (acc.max() - acc.min() + 1e-6)


# ---- land data (equirectangular), cached -------------------------------------
def land_textures():
    p = os.path.join(CACHE, "land.npz")
    if os.path.exists(p):
        d = np.load(p)
        return d["cov"], d["inland"], d["shelf"], d["offshore"]
    import global_land_mask.globe as g
    m = ~g._mask  # _mask is True over ocean; (21600, 43200) lat 90..-90, lon -180..180
    cov = m.reshape(5400, 4, 10800, 4).mean(axis=(1, 3)).astype(np.float32)
    small = cov.reshape(2700, 2, 5400, 2).mean(axis=(1, 3)) > 0.5
    # distance in pixels at 15 px/deg
    din = ndimage.distance_transform_edt(small).astype(np.float32)
    dout = ndimage.distance_transform_edt(~small).astype(np.float32)
    lab, nlab = ndimage.label(small)
    sizes = ndimage.sum(small, lab, np.arange(1, nlab + 1))
    major = np.isin(lab, np.nonzero(sizes > 2500)[0] + 1)
    dmaj = ndimage.distance_transform_edt(~major).astype(np.float32)
    inland = np.clip(din / 120.0, 0, 1)  # 0 at coast -> 1 deep inland (~8 deg)
    shelf = np.exp(-dout / 10.0)  # 1 at coast, fades over ~0.7 deg
    inland = ndimage.zoom(inland, 2, order=1)
    shelf = ndimage.zoom(shelf, 2, order=1)
    offshore = ndimage.zoom(ndimage.gaussian_filter(dmaj, 2.0) / 15.0, 2, order=1).astype(np.float32)  # deg from major coasts
    np.savez_compressed(p, cov=cov, inland=inland, shelf=shelf, offshore=offshore)
    return cov, inland, shelf, offshore


def sample_eq(tex, lat, lon):
    h, w = tex.shape
    r = (90 - lat) / 180 * h - 0.5
    c = ((lon + 180) % 360) / 360 * w - 0.5
    return ndimage.map_coordinates(tex, [r, c], order=1, mode="wrap")


def clouds_eq():
    p = os.path.join(CACHE, "clouds.npy")
    if os.path.exists(p):
        return np.load(p)
    h, w = 1000, 2000
    base = fbm_wrap((h, w), 7, 6, seed=31, persistence=0.62)
    wx = fbm_wrap((h, w), 5, 3, seed=32) - 0.5
    wy = fbm_wrap((h, w), 5, 3, seed=33) - 0.5
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # swirl + strong east-west stretch, like jet-stream cloud bands
    warped = ndimage.map_coordinates(base, [yy + wy * 90, xx + wx * 420], order=1, mode="wrap")
    detail = fbm_wrap((h, w), 5, 40, seed=34, persistence=0.6)
    c = smoothstep(0.60, 0.86, warped * 0.8 + detail * 0.2)
    lat = 90 - (yy + 0.5) / h * 180
    band = 0.55 + 0.45 * np.cos(np.radians(lat) * 3.2) ** 2  # fewer clouds in subtropics
    c = (c * band).astype(np.float32)
    np.save(p, c)
    return c


def currents_eq():
    """Smooth, east-west flowing scalar field; its contour lines read as ocean currents."""
    p = os.path.join(CACHE, "currents.npy")
    if os.path.exists(p):
        return np.load(p)
    h, w = 900, 1800
    base = fbm_wrap((h, w), 4, 2, seed=51, persistence=0.5)
    wx = fbm_wrap((h, w), 4, 3, seed=52) - 0.5
    wy = fbm_wrap((h, w), 4, 3, seed=53) - 0.5
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    f = ndimage.map_coordinates(base, [yy + wy * 60, xx + wx * 260], order=1, mode="wrap")
    f = f * 0.6 + (yy / h) * 0.9  # bias toward latitude bands -> mostly zonal flow
    f = ndimage.gaussian_filter(f, 3).astype(np.float32)
    np.save(p, f)
    return f


# ---- camera ------------------------------------------------------------------
LAT0, LON0, ROLL = np.radians(-3.0), np.radians(114.0), np.radians(-14.0)
CX, CY, R = W * 0.5, H * 0.415, H * 0.465


def rot_matrix():
    # world: x toward (lat0,lon0) eye ... build view basis
    cl, sl = np.cos(LAT0), np.sin(LAT0)
    co, so = np.cos(LON0), np.sin(LON0)
    fwd = np.array([cl * co, cl * so, sl])  # points at viewer
    east = np.array([-so, co, 0.0])
    north = np.cross(fwd, east)
    cr, sr = np.cos(ROLL), np.sin(ROLL)
    right = cr * east + sr * north
    up = -sr * east + cr * north
    return np.stack([right, up, fwd])  # rows: view x, y, z in world coords


M = rot_matrix()


def ll_to_world(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1)


def project(p):
    """world xyz (radius >= 1) -> screen x, y, view z."""
    v = p @ M.T
    return CX + R * v[..., 0], CY - R * v[..., 1], v[..., 2]


# ---- main render ---------------------------------------------------------------
def render():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx + 0.5 - CX) / R
    ny = -(yy + 0.5 - CY) / R
    rr = np.sqrt(nx ** 2 + ny ** 2)
    inside = rr < 1.0
    aa = np.clip((1.0 - rr) * R / 1.2, 0, 1)  # anti-aliased disk edge

    L = np.array([0.80, 0.46, 0.36]); L /= np.linalg.norm(L)  # key light (upper right, front)
    sun_dir2d = np.array([0.885, 0.465])  # where the sun peeks over the limb

    # ---------- background: deep space ----------
    d_center = np.sqrt(((xx - W * 0.5) / W) ** 2 + ((yy - H * 0.45) / H) ** 2)
    img = ramp(1 - np.clip(d_center * 1.25, 0, 1), [(0, NAVY_0), (0.6, NAVY_1 * 0.9), (1, NAVY_1 * 1.05)])
    neb = fbm((H, W), 6, 3, seed=3)
    neb2 = fbm((H, W), 5, 2, seed=11)
    img += (BLUE_3 * 0.10) * (smoothstep(0.45, 0.9, neb) ** 1.5)[..., None]
    img += (ORANGE * 0.05) * (smoothstep(0.55, 0.95, neb2) * smoothstep(0.2, 1.0, xx / W) * smoothstep(0.7, 0.0, yy / H))[..., None]

    # depth: rich blue halo pooled behind the globe, falling off into near-black corners
    dg_ = np.sqrt(((xx - CX) / R) ** 2 + ((yy - CY) / R) ** 2)
    halo = np.exp(-np.clip(dg_ - 0.95, 0, None) / 0.38)
    img = img * (0.35 + 0.65 * smoothstep(2.2, 0.95, dg_))[..., None]
    img += (halo * 0.30)[..., None] * mix(NAVY_2, BLUE_3, 0.5)
    img += (np.exp(-np.clip(dg_ - 1.0, 0, None) / 0.18) * 0.22)[..., None] * BLUE_3

    # a faint galactic band crossing behind the globe (dust lanes + warm core)
    band_d = ((xx - W * 0.5) / W) * 0.42 + ((yy - H * 0.5) / H) * 0.62
    band = np.exp(-(band_d / 0.11) ** 2)
    dust = fbm((H, W), 7, 6, seed=41, persistence=0.62)
    lanes = smoothstep(0.42, 0.68, fbm((H, W), 6, 9, seed=42, persistence=0.6))
    img += (band * smoothstep(0.35, 0.85, dust) * (1 - 0.8 * lanes) * 0.13)[..., None] * mix(BLUE_4, BLUE_5, 0.3)
    img += (band ** 3 * smoothstep(0.5, 0.9, dust) * 0.07)[..., None] * PEACH

    # stars
    star = np.zeros((H, W), np.float32)
    n = int(2600 * SCALE * SCALE * 4)
    sx, sy = rng.random(n) * W, rng.random(n) * H
    # extra faint stars concentrated in the galactic band
    m2 = int(5000 * SCALE * SCALE * 4)
    bx, by = rng.random(m2 * 3) * W, rng.random(m2 * 3) * H
    bd = ((bx - W * 0.5) / W) * 0.42 + ((by - H * 0.5) / H) * 0.62
    keep = rng.random(m2 * 3) < np.exp(-(bd / 0.09) ** 2)
    sx, sy = np.concatenate([sx, bx[keep]]), np.concatenate([sy, by[keep]])
    n = len(sx)
    mag = rng.random(n) ** 6
    star[sy.astype(int), sx.astype(int)] += 0.25 + 1.6 * mag
    bigs = np.zeros((H, W), np.float32)
    sel = mag > 0.35
    bigs[sy[sel].astype(int), sx[sel].astype(int)] = mag[sel]
    starglow = ndimage.gaussian_filter(bigs, 2.2 * SCALE * 2) * 7
    star = ndimage.gaussian_filter(star, 0.6 * SCALE * 2) * 3 + starglow
    tint = mix(BLUE_5, PEACH, (rng.random((H, W)) > 0.6).astype(np.float32) * 0.0 + neb2)
    img += star[..., None] * tint * (1 - inside[..., None])

    # ---------- globe ----------
    nz = np.sqrt(np.clip(1 - rr ** 2, 0, 1))
    N = np.stack([nx, ny, nz], -1)
    world = N @ M  # view -> world
    lat = np.degrees(np.arcsin(np.clip(world[..., 2], -1, 1)))
    lon = np.degrees(np.arctan2(world[..., 1], world[..., 0]))

    cov, inland, shelf, offshore = land_textures()
    idx = np.where(inside)
    la, lo = lat[idx], lon[idx]
    land = np.zeros((H, W), np.float32); land[idx] = sample_eq(cov, la, lo)
    inl = np.zeros((H, W), np.float32); inl[idx] = sample_eq(inland, la, lo)
    shf = np.zeros((H, W), np.float32); shf[idx] = sample_eq(shelf, la, lo)
    off = np.zeros((H, W), np.float32); off[idx] = sample_eq(offshore, la, lo)
    cur = np.zeros((H, W), np.float32); cur[idx] = sample_eq(currents_eq(), la, lo)
    land = smoothstep(0.35, 0.65, land)
    land_full = land.copy()
    land *= smoothstep(-64, -56, lat)  # keep Antarctica out of the title area

    # painterly texture anchored to the sphere (sample noise in lat/lon space)
    eq_noise = fbm_wrap((900, 1800), 7, 6, seed=21, persistence=0.6)
    eq_noise2 = fbm_wrap((900, 1800), 6, 12, seed=5, persistence=0.65)
    tex = np.zeros((H, W), np.float32); tex[idx] = sample_eq(eq_noise, la, lo)
    tex2 = np.zeros((H, W), np.float32); tex2[idx] = sample_eq(eq_noise2, la, lo)

    ndl = (N @ L).astype(np.float32)
    day = smoothstep(-0.10, 0.22, ndl)
    diffuse = np.clip(ndl, 0, 1) ** 0.85

    # ocean
    ocean_t = 0.04 + 0.92 * diffuse
    ocean = ramp(ocean_t, [(0, NAVY_1 * 0.8), (0.4, NAVY_2), (0.8, BLUE_3), (1.0, mix(BLUE_3, BLUE_4, 0.5))])
    ocean = mix(ocean, mix(BLUE_3, BLUE_4, 0.7), (shf ** 1.4) * 0.6 * day)  # shallow shelves
    # brush streaks in water + deeper tone far from the coasts
    ocean *= (1 - 0.22 * smoothstep(0.5, 9.0, off))[..., None]

    # engraved ocean layers (kept faint): bathymetric contours that echo every coastline,
    # and long flowing current lines across the open sea
    def contour(F, step, width=0.9):
        gF = np.abs(np.gradient(F, axis=0)) + np.abs(np.gradient(F, axis=1)) + 1e-5
        dd = np.abs(F / step - np.round(F / step)) * step
        return np.exp(-(dd / (gF * width)) ** 2)
    sea = (1 - smoothstep(0.05, 0.5, land)) * inside
    vis = 0.35 + 0.65 * day
    bathy = contour(off, 1.1, 0.7) * np.exp(-off / 3.2) * (off > 0.25)
    flow = contour(cur, 0.035, 0.7) * smoothstep(0.6, 2.5, off)
    ocean_lines = (bathy * 0.21 + flow * 0.15) * sea * vis * nz ** 0.6
    # dotted mid-ocean texture (very light halftone, grows with depth)
    gs = 9 * SCALE * 2
    dots = (np.sin(xx * np.pi / gs) * np.sin(yy * np.pi / gs)) ** 2
    dots = smoothstep(0.80, 0.97, dots) * smoothstep(3.0, 12.0, off) * sea * 0.05 * vis

    # land: cream -> sand -> gold with inland relief and painterly mottling
    relief = np.clip(0.55 * inl + 0.6 * (tex - 0.5) + 0.25, 0, 1)
    land_lit = ramp(relief, [(0, CREAM), (0.35, PEACH), (0.65, SAND), (1, GOLD)])
    land_lit = mix(land_lit, GOLD_D, smoothstep(0.62, 0.95, tex) * 0.35)
    shade = 0.22 + 1.12 * diffuse
    land_col = land_lit * shade[..., None]
    land_col = mix(land_col, BRONZE * 0.7, (1 - day) * 0.0)

    surf = mix(ocean, land_col, land)
    surf += (ocean_lines)[..., None] * mix(BLUE_4, BLUE_5, 0.6) + dots[..., None] * BLUE_5

    # night side: deep navy, land slightly visible
    night = mix(mix(NAVY_0, NAVY_1, 0.55), mix(NAVY_1 * 0.8, BRONZE * 0.45, 0.45), land * 0.85)
    surf = mix(night, surf, day)

    # warm key light / cool fill
    warm = smoothstep(0.15, 1.0, diffuse)[..., None]
    surf *= np.array([0.90, 0.97, 1.10]) * (1 - warm) + np.array([1.14, 1.0, 0.80]) * warm

    # coastline highlight (illustrative ink edge)
    edge = np.clip(land * (1 - land) * 4, 0, 1)
    surf += (edge * 0.35 * day)[..., None] * CREAM

    # terminator warm band (golden hour across the day/night line)
    term = np.exp(-((ndl - 0.0) / 0.13) ** 2)
    surf += (0.55 * term * (0.08 + 0.92 * land))[..., None] * mix(ORANGE_D, ORANGE, 0.6)
    surf += (0.25 * np.exp(-((ndl - 0.12) / 0.10) ** 2) * land)[..., None] * PEACH

    # graticule: thin gold meridians/parallels every 15 deg (gives the sphere its curvature)
    glat = np.abs(np.gradient(lat, axis=0)) + np.abs(np.gradient(lat, axis=1)) + 1e-4
    lon_c = np.where(np.abs(lon) > 170, (lon + 360) % 360, lon)
    glon = np.abs(np.gradient(lon_c, axis=0)) + np.abs(np.gradient(lon_c, axis=1)) + 1e-4
    dlat = np.abs(lat / 15 - np.round(lat / 15)) * 15
    dlon = np.abs(lon / 15 - np.round(lon / 15)) * 15
    grat = np.maximum(np.exp(-(dlat / (glat * 0.9)) ** 2), np.exp(-(dlon / (glon * 0.9)) ** 2) * (np.abs(lat) < 75))
    surf += (grat * inside * (0.05 + 0.13 * day) * nz ** 0.8)[..., None] * SAND

    # specular sun glint on ocean
    V = np.array([0, 0, 1.0])
    Hv = (L + V) / np.linalg.norm(L + V)
    spec = np.clip(N @ Hv, 0, 1) ** 220
    spec_wide = np.clip(N @ Hv, 0, 1) ** 25
    surf += ((0.0 * spec)[..., None] * PEACH + (0.0 * spec_wide)[..., None] * ORANGE) * (1 - land[..., None])

    # ---------- city lights (night side + gentle on terminator) ----------
    lights = np.zeros((H, W), np.float32)
    try:
        cities = json.load(open(CITIES))
        cl = np.array([[float(c["lat"]), float(c["lng"])] for c in cities], np.float32)
        p = ll_to_world(cl[:, 0], cl[:, 1])
        px, py, pz = project(p)
        ok = (pz > 0.03) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
        px, py = px[ok].astype(int), py[ok].astype(int)
        w = 0.35 + rng.random(len(px)) ** 3 * 1.6
        np.add.at(lights, (py, px), w)
    except FileNotFoundError:
        pass
    sp = SCALE * 2  # 2 at print size
    lights_core = ndimage.gaussian_filter(lights, 0.42 * sp)
    lights_mid = ndimage.gaussian_filter(lights, 1.6 * sp)
    lights_glow = ndimage.gaussian_filter(lights, 7.0 * sp)
    nightness = (1 - smoothstep(-0.22, 0.10, ndl)) * nz ** 0.4
    core = 1.9 * (1 - np.exp(-lights_core * 2.4 * sp * sp))
    mid = 0.9 * (1 - np.exp(-lights_mid * 3.0 * sp * sp))
    glow = 0.45 * (1 - np.exp(-lights_glow * 6.0 * sp * sp))
    surf += (core * nightness)[..., None] * mix(CREAM, PEACH, 0.3)
    surf += (mid * nightness)[..., None] * mix(SAND, ORANGE, 0.25) * 0.8
    surf += (glow * nightness)[..., None] * mix(ORANGE, ORANGE_D, 0.4) * 0.45

    # painted cloud veil: domain-warped, zonally stretched noise anchored to the globe
    cw = clouds_eq()
    cl_ = np.zeros((H, W), np.float32); cl_[idx] = sample_eq(cw, la, lo)
    cloud_col = mix(mix(BLUE_5, CREAM, 0.6), PEACH, smoothstep(0.1, 0.0, ndl) * 0.0)
    cloud_lit = (0.18 + 0.9 * diffuse)[..., None] * cloud_col
    cloud_lit += (0.6 * term)[..., None] * ORANGE * cl_[..., None]


    # limb darkening + fresnel atmosphere inside the disk
    fres = (1 - nz) ** 2.6
    lit_side = smoothstep(-0.4, 0.6, ndl)
    surf *= (0.55 + 0.45 * nz ** 0.35)[..., None]
    fres = (1 - nz) ** 3.4
    atm_in = mix(BLUE_3, BLUE_4, lit_side) * (fres * (0.06 + 0.85 * lit_side) * (1 - 0.5 * land))[..., None]
    surf += atm_in

    img = mix(img, surf, aa)

    # ---------- outer atmosphere ----------
    d = (rr - 1.0) * R  # px outside the limb
    ang = np.arctan2(ny, nx)
    facing = (nx * L[0] + ny * L[1]) / (np.sqrt(nx ** 2 + ny ** 2) + 1e-6)
    facing = np.clip(0.5 + 0.5 * facing, 0, 1)
    outside = d > 0
    thin = np.exp(-np.clip(d, 0, None) / (10 * SCALE * 2)) * outside
    wide = np.exp(-np.clip(d, 0, None) / (90 * SCALE * 2)) * outside
    huge = np.exp(-np.clip(d, 0, None) / (380 * SCALE * 2)) * outside
    img += (0.8 * thin * (0.25 + facing ** 1.5))[..., None] * BLUE_5
    img += (0.26 * wide * (0.1 + facing ** 2))[..., None] * BLUE_4
    img += (0.12 * huge * (0.2 + facing))[..., None] * BLUE_3
    # bright inner rim line on the lit side
    rim = np.exp(-((rr - 0.997) * R / (3.5 * SCALE * 2)) ** 2)
    img += (rim * facing ** 2 * 0.5)[..., None] * mix(BLUE_5, CREAM, 0.4)
    # sunrise crescent: the limb nearest the sun burns warm orange -> cream
    sun_ang = np.arctan2(sun_dir2d[1], sun_dir2d[0])
    dang = np.angle(np.exp(1j * (np.arctan2(ny, nx) - sun_ang)))
    near_sun = np.exp(-(dang / 0.55) ** 2)
    crescent = np.exp(-((rr - 0.995) * R / (9 * SCALE * 2)) ** 2) + 0.5 * np.exp(-((rr - 1.0) * R / (30 * SCALE * 2)) ** 2)
    img += (crescent * near_sun * 0.45)[..., None] * mix(ORANGE, PEACH, near_sun)

    # sun peeking over the limb: warm flare
    sun = np.array([CX + R * sun_dir2d[0] * 1.0, CY - R * sun_dir2d[1] * 1.0])
    ds = np.sqrt((xx - sun[0]) ** 2 + (yy - sun[1]) ** 2) / (R)
    flare = np.exp(-ds / 0.025) * 0.9 + np.exp(-ds / 0.09) * 0.32 + np.exp(-ds / 0.35) * 0.12
    occl = np.where(inside, 0.35 + 0.65 * smoothstep(0.93, 1.0, rr), 1.0)
    img += mix(ORANGE, PEACH, np.clip(np.exp(-ds / 0.04), 0, 1)) * (flare * occl)[..., None]
    # anamorphic streak (very subtle)
    streak = np.exp(-((yy - sun[1]) / (5 * SCALE * 2)) ** 2) * np.exp(-np.abs(xx - sun[0]) / (W * 0.22))
    streak = np.exp(-((yy - sun[1]) / (3 * SCALE * 2)) ** 2) * np.exp(-np.abs(xx - sun[0]) / (W * 0.08))


    # ---------- connection arcs ----------
    arcs = render_arcs()
    img = img + arcs[..., :3]
    # ---------- finishing: vignette, title fade, plane, bloom ----------
    vig = smoothstep(1.15, 0.35, np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.45) / (H * 0.70)) ** 2))
    img *= (0.45 + 0.55 * vig)[..., None]

    # bottom fade into navy for the title area
    bf = smoothstep(0.50, 0.97, yy / H)
    img = mix(img, NAVY_0 * 1.1, bf * 0.72)

    orbit = render_orbit()
    img = img * (1 - orbit[..., 3:4]) + orbit[..., :3]

    lum = img.mean(-1)
    bright = np.clip(img - 0.75, 0, None) * smoothstep(0.75, 1.3, lum)[..., None]
    bloom = np.stack([ndimage.gaussian_filter(bright[..., c], 18 * SCALE * 2) for c in range(3)], -1)
    img += bloom * 0.3

    # gentle contrast + saturation lift
    lum = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    img = lum[..., None] + (img - lum[..., None]) * 1.22
    img = np.clip(img, 0, None)
    img = img ** 1.14

    # filmic tone map (soft shoulder keeps highlights from clipping)
    img = 1 - np.exp(-img * 1.6)
    grain = rng.normal(0, 1, (H, W)).astype(np.float32)
    grain = ndimage.gaussian_filter(grain, 0.6) * 0.028
    img += grain[..., None]
    return np.clip(img, 0, 1)


PARTNERS = {
    # name: (lat, lon)
    "UTS Sydney": (-33.88, 151.20),
    "Bennett University": (28.45, 77.58),
    "Singapore Polytechnic": (1.31, 103.78),
    "UNITEN Malaysia": (2.97, 101.73),
    "RMIT Melbourne": (-37.81, 144.96),
    "Seoul": (37.55, 126.99),
    "Tokyo": (35.68, 139.69),
}
HOME = (10.77, 106.66)  # HCMUT, Ho Chi Minh City


def great_arc(a, b, n=400):
    pa, pb = ll_to_world(*a), ll_to_world(*b)
    om = np.arccos(np.clip(pa @ pb, -1, 1))
    t = np.linspace(0, 1, n)
    s = (np.sin((1 - t) * om)[:, None] * pa + np.sin(t * om)[:, None] * pb) / np.sin(om)
    hmax = 0.03 + 0.30 * om
    alt = 1 + hmax * np.sin(np.pi * t)
    return s * alt[:, None], t


def render_arcs():
    ss = 2  # supersample for clean lines
    big = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    glow = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    dr, dg = ImageDraw.Draw(big), ImageDraw.Draw(glow)
    lw = max(1, int(2.2 * SCALE * 2 * ss))

    def col(c, a):
        return tuple(int(v * 255) for v in c) + (int(a * 255),)

    for i, (name, ll) in enumerate(PARTNERS.items()):
        pts, t = great_arc(HOME, ll)
        x, y, z = project(pts)
        r2 = np.sqrt(((x - CX) / R) ** 2 + ((y - CY) / R) ** 2)
        visible = (z > 0) | (r2 > 1.0)
        c_a, c_b = (GOLD, ORANGE) if i % 2 == 0 else (PEACH, SAND)
        for k in range(len(t) - 1):
            if not (visible[k] and visible[k + 1]):
                continue
            tt = t[k]
            a = 0.25 + 0.75 * np.sin(np.pi * min(1, tt * 1.0)) ** 0.5
            a *= 0.55 + 0.45 * tt  # brighter toward destination
            c = c_a * (1 - tt) + c_b * tt
            seg = [(x[k] * ss, y[k] * ss), (x[k + 1] * ss, y[k + 1] * ss)]
            dr.line(seg, fill=col(c, a), width=lw)
            dg.line(seg, fill=col(c, a * 0.3), width=lw * 3)
        # destination node
        if visible[-1]:
            ex, ey = x[-1] * ss, y[-1] * ss
            rad = 5 * SCALE * 2 * ss
            dr.ellipse([ex - rad, ey - rad, ex + rad, ey + rad], fill=col(CREAM, 1))

            ring = rad * 2.6
            dr.ellipse([ex - ring, ey - ring, ex + ring, ey + ring], outline=col(PEACH, 0.55), width=max(1, lw // 2))

    # home: Ho Chi Minh City
    hx, hy, _ = project(ll_to_world(*HOME))
    hx, hy = hx * ss, hy * ss
    rad = 9 * SCALE * 2 * ss
    dr.ellipse([hx - rad, hy - rad, hx + rad, hy + rad], fill=col(CREAM, 1))
    dg.ellipse([hx - rad * 4, hy - rad * 4, hx + rad * 4, hy + rad * 4], fill=col(ORANGE, 1))
    for k, a in ((2.2, 0.8), (3.6, 0.45), (5.4, 0.22)):
        rk = rad * k
        dr.ellipse([hx - rk, hy - rk, hx + rk, hy + rk], outline=col(PEACH, a), width=max(1, lw))

    big = big.resize((W, H), Image.LANCZOS)
    glow = glow.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(10 * SCALE * 2))
    a = np.asarray(big, np.float32) / 255
    g = np.asarray(glow, np.float32) / 255
    rgb = a[..., :3] * a[..., 3:4] * 1.15 + g[..., :3] * g[..., 3:4] * 0.7
    return np.concatenate([rgb, a[..., 3:4]], -1)


def render_orbit():
    """Tilted orbit trail around the globe ending in a paper plane (echoes the ISC logo)."""
    ss = 3
    sp = SCALE * 2
    lay = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    glow = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    dl, dg = ImageDraw.Draw(lay), ImageDraw.Draw(glow)
    roll = np.radians(-13)
    u = np.array([np.cos(roll), np.sin(roll), 0.0])
    v = np.array([0.0, -0.24, 0.97]); v -= u * (u @ v); v /= np.linalg.norm(v)
    ro = 1.13
    t = np.linspace(1.12 * np.pi, 0.06 * np.pi, 1700)
    P = ro * (np.cos(t)[:, None] * u + np.sin(t)[:, None] * v)
    x, y, z = CX + R * P[:, 0], CY - R * P[:, 1], P[:, 2]
    hidden = (z < 0) & (P[:, 0] ** 2 + P[:, 1] ** 2 < 1)
    prog = np.linspace(0, 1, len(t))

    def col(c, a):
        return tuple(int(np.clip(v_, 0, 1) * 255) for v_ in c) + (int(np.clip(a, 0, 1) * 255),)

    def stamp(d, px, py, w, fill):
        r = w / 2
        d.ellipse([px - r, py - r, px + r, py + r], fill=fill)

    for k in range(len(t) - 1):
        if hidden[k] or hidden[k + 1]:
            continue
        p = prog[k]
        a = 0.38 + 0.62 * p ** 1.3
        c = ramp(np.array(p), [(0, GOLD_D), (0.4, ORANGE), (0.8, SAND), (1, CREAM)])
        wdt = (3.2 + 9.5 * p ** 1.5) * (0.75 + 0.25 * (z[k] + 1)) * sp * ss
        px, py = x[k] * ss, y[k] * ss
        stamp(dl, px, py, wdt, col(c, a))
        if p > 0.55:  # hot white core on the leading stretch
            stamp(dl, px, py, wdt * 0.38, col(CREAM, ((p - 0.55) / 0.45) ** 1.2))
        stamp(dg, px, py, wdt * 3, col(mix(ORANGE, PEACH, p), a * 0.25))

    lay = lay.resize((W, H), Image.LANCZOS)
    glow = glow.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(10 * sp))
    a = np.asarray(lay, np.float32) / 255
    g = np.asarray(glow, np.float32) / 255
    rgb = a[..., :3] * a[..., 3:4] + g[..., :3] * g[..., 3:4] * 0.4
    alpha = a[..., 3:4].copy()

    # ---- paper plane, shaded faces, at the head of the trail ----
    hx, hy = x[-1], y[-1]
    dx, dy = x[-1] - x[-40], y[-1] - y[-40]
    f = np.array([dx, dy]) / np.hypot(dx, dy)
    nrm = np.array([-f[1], f[0]])
    sz = 150 * sp  # px at final size
    TAIL = (-0.40, -0.05)
    cx0 = hx - (f[0] * TAIL[0] + nrm[0] * TAIL[1]) * sz
    cy0 = hy - (f[1] * TAIL[0] + nrm[1] * TAIL[1]) * sz
    box = int(sz * 2.6)
    x0, y0 = int(cx0 - box / 2), int(cy0 - box / 2)
    S = 4  # local supersampling
    yy, xx = np.mgrid[0:box * S, 0:box * S].astype(np.float32)
    gx, gy = x0 + (xx + 0.5) / S, y0 + (yy + 0.5) / S
    la = ((gx - cx0) * f[0] + (gy - cy0) * f[1]) / sz  # along flight
    lb = ((gx - cx0) * nrm[0] + (gy - cy0) * nrm[1]) / sz  # across

    def tri(p0, p1, p2):
        def side(a_, b_):
            return (lb - a_[1]) * (b_[0] - a_[0]) - (la - a_[0]) * (b_[1] - a_[1])
        s0, s1, s2 = side(p0, p1), side(p1, p2), side(p2, p0)
        return (((s0 >= 0) & (s1 >= 0) & (s2 >= 0)) | ((s0 <= 0) & (s1 <= 0) & (s2 <= 0))).astype(np.float32)

    NOSE, WL, C, K, WR = (1.0, 0.0), (-0.80, -0.98), (-0.40, -0.05), (-0.60, 0.20), (-0.78, 0.56)
    top, keel, low = tri(NOSE, WL, C), tri(NOSE, C, K), tri(NOSE, K, WR)
    keel *= 1 - top
    low *= (1 - top) * (1 - keel)
    tn = np.clip((la + 0.9) / 1.9, 0, 1)  # 0 tail -> 1 nose
    c_top = ramp(tn * 0.75 + np.clip(-lb, 0, 1) * 0.25, [(0, mix(PEACH, SAND, 0.4) * 0.95), (0.45, PEACH * 1.08), (0.8, CREAM), (1, np.array([1.0, 0.99, 0.96], np.float32))])
    # soft shadow where the top wing meets the fold
    c_top *= (1 - 0.35 * np.exp(-((lb - C[1] * (la - 1.0) / (C[0] - 1.0)) / 0.06) ** 2) * (la < 1.0))[..., None]
    c_keel = ramp(tn, [(0, ORANGE_D * 0.8), (0.6, ORANGE), (1, PEACH)])
    c_low = ramp(tn, [(0, NAVY_2), (0.6, BLUE_3), (1, BLUE_4)])
    pcol = c_top * top[..., None] + c_keel * keel[..., None] + c_low * low[..., None]
    pa = np.clip(top + keel + low, 0, 1)
    # bright leading edges
    edge = (np.abs(lb - (WL[1] / (WL[0] - 1.0)) * (la - 1.0)) < 0.018) * (la > WL[0]) * (la < 1.0)
    edge = edge.astype(np.float32) * pa
    pcol = pcol * (1 - edge[..., None] * 0.8) + CREAM * edge[..., None] * 0.8

    def down(arr):
        return arr.reshape(box, S, box, S, *arr.shape[2:]).mean(axis=(1, 3))

    pcol, pa = down(pcol * pa[..., None]), down(pa)
    # paste into full-size layers (clip at canvas edge)
    X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(W, x0 + box), min(H, y0 + box)
    sl = (slice(Y0 - y0, Y1 - y0), slice(X0 - x0, X1 - x0))
    # soft drop shadow below the plane (separates it from the bright limb without a glow)
    sh = np.zeros((H, W), np.float32)
    off_x, off_y = int(0.10 * sz), int(0.16 * sz)
    sh[min(H, Y0 + off_y):min(H, Y1 + off_y), min(W, X0 + off_x):min(W, X1 + off_x)] = \
        pa[sl][: max(0, min(H, Y1 + off_y) - min(H, Y0 + off_y)), : max(0, min(W, X1 + off_x) - min(W, X0 + off_x))]
    sh = ndimage.gaussian_filter(sh, sz * 0.10) * 0.45
    alpha[..., 0] = np.maximum(alpha[..., 0], sh)
    rgb[Y0:Y1, X0:X1] = rgb[Y0:Y1, X0:X1] * (1 - pa[sl][..., None]) + pcol[sl]
    alpha[Y0:Y1, X0:X1, 0] = np.maximum(alpha[Y0:Y1, X0:X1, 0], pa[sl])
    return np.concatenate([rgb, alpha], -1)


def add_title(im):
    im = im.convert("RGBA")
    d = ImageDraw.Draw(im)
    bebas = os.path.join(FONTS, "bebas-neue-latin-400-normal.ttf")
    mont = os.path.join(FONTS, "montserrat-latin-500-normal.ttf")
    cream = (255, 240, 214, 255)

    def centered(text, font, y, fill, tracking=0):
        widths = [font.getlength(ch) for ch in text]
        total = sum(widths) + tracking * (len(text) - 1)
        x = (W - total) / 2
        for ch, w in zip(text, widths):
            d.text((x, y), ch, font=font, fill=fill)
            x += w + tracking

    f_tag = ImageFont.truetype(mont, int(46 * SCALE))
    f1 = ImageFont.truetype(bebas, int(300 * SCALE))
    f2 = ImageFont.truetype(bebas, int(300 * SCALE))
    # soft shadow layer for legibility
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow)
    y1, y2 = H * 0.675, H * 0.805
    for txt, f, y in (("INTERNATIONAL", f1, y1), ("STUDENT CONNECTION", f2, y2)):
        w = f.getlength(txt) + 6 * SCALE * (len(txt) - 1)
        ds.text(((W - w) / 2, y), txt, font=f, fill=(2, 8, 25, 200))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28 * SCALE))
    im = Image.alpha_composite(im, shadow)
    d = ImageDraw.Draw(im)
    centered("CONNECT  ·  LEARN  ·  GROW TOGETHER", f_tag, H * 0.640, cream, tracking=6 * SCALE)
    centered("INTERNATIONAL", f1, y1, cream, tracking=6 * SCALE)
    centered("STUDENT CONNECTION", f2, y2, cream, tracking=6 * SCALE)
    return im.convert("RGB")


if __name__ == "__main__":
    art = render()
    out = Image.fromarray((art * 255 + 0.5).astype(np.uint8))
    tag = "" if SCALE >= 1 else f"_preview"
    out.save(os.path.join(HERE, f"isc_cover_art{tag}.png"))
    add_title(out).save(os.path.join(HERE, f"isc_cover_with_title{tag}.png"))
    print("done", W, H)
