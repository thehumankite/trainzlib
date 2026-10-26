#!/usr/bin/env python3
"""
trainzlib.py - read Trainz 'tzMF' meshes (.trainzmesh), JIRF/IDXM models (.im) and 'JIRF' animations (.kin),
export to Wavefront OBJ (optionally posed) and skinned+animated glTF binary (.glb).
Format notes: see TRAINZ_FORMAT.md.  Everything here is reverse-engineered from one
mesh + one animation; unknowns are marked UNVERIFIED.

CLI:
  python trainzlib.py info  mesh.trainzmesh [anim.kin]
  python trainzlib.py obj   mesh.trainzmesh out.obj [--kin anim.kin --frame 7.5]
  python trainzlib.py glb   mesh.trainzmesh out.glb [--kin anim.kin]
  (mesh may be a .trainzmesh or a .im; kin vs .im: auto-detects world/local space)
"""
import argparse, json, math, os, re, shutil, struct, sys, urllib.parse
import numpy as np

# ----------------------------------------------------------------- helpers
def lstr(d, p):
    """u32 LE length (includes trailing NUL) + bytes -> (str, new_p)"""
    (n,) = struct.unpack_from('<I', d, p)
    return d[p + 4:p + 4 + n].rstrip(b'\0').decode('ascii'), p + 4 + n

TOKENS = {'P3f': ('p', '<f4', 3), 'Wi4B': ('wi', 'u1', 4), 'Wg4f': ('wg', '<f4', 4),
          'N3f': ('n', '<f4', 3), 'Tg3f': ('t', '<f4', 3), 'T02f': ('uv', '<f4', 2),
          'T12f': ('uv1', '<f4', 2)}

def layout_dtype(layout):
    toks = re.findall(r'P3f|Wi4B|Wg4f|N3f|Tg3f|T\d2f', layout.split('_', 1)[1])
    return np.dtype([TOKENS[t] for t in toks])

def quat_mat(q):
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def trs(pos, quat, scale=(1, 1, 1)):
    m = np.eye(4)
    m[:3, :3] = quat_mat(quat) * np.array(scale)[None, :]
    m[:3, 3] = pos
    return m

# ----------------------------------------------------------------- mesh
STD_VERT = np.dtype([('p', '<f4', 3), ('wi', 'u1', 4), ('wg', '<f4', 4), ('n', '<f4', 3), ('uv', '<f4', 2)])

def normalize_verts(v, tris):
    """Static/unskinned layouts (e.g. P3f_N3f_T02f) lack weights, normals or UVs. Return a standard array that always
    has p, wi, wg, n, uv: missing weights bind 100% to bone 0, missing normals are computed, missing UVs are 0."""
    have = v.dtype.names or ()
    out = np.zeros(len(v), STD_VERT)
    out['p'] = v['p']
    if 'wi' in have: out['wi'] = v['wi']
    if 'wg' in have:
        out['wg'] = v['wg']
    else:
        out['wg'][:, 0] = 1.0
    if 'n' in have:
        out['n'] = v['n']
    elif len(tris):
        P = v['p'].astype(float)
        fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
        n = np.zeros_like(P)
        for k in range(3): np.add.at(n, tris[:, k], fn)
        out['n'] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    if 'uv' in have: out['uv'] = v['uv']
    return out

def read_mesh(d):
    if d[:4] != b'tzMF':
        raise ValueError('not tzMF')
    ver, unk, nb, nsub, z, ntri = struct.unpack_from('>6I', d, 4)
    bounds = struct.unpack_from('>6f', d, 0x1c)
    p, bones = 0x34, []
    for _ in range(nb):
        l = d[p]; name = d[p+1:p+1+l].decode(); p += 1 + l
        l = d[p]; par = d[p+1:p+1+l].decode(); p += 1 + l
        r = struct.unpack_from('>7f', d, p); p += 28
        bones.append(dict(name=name, parent=par, pos=r[:3], quat=r[3:]))
    subs = []
    for _ in range(nsub):
        assert d[p:p+8] == bytes(8), 'submesh header misaligned @%x' % p
        p += 8
        (k,) = struct.unpack_from('<I', d, p); p += 4          # always 3 (UNVERIFIED meaning)
        assert d[p] == 0x0d; p += 1
        tag = d[p:p+4]; p += 4                                  # opaque 4 bytes (UNVERIFIED)
        layout, p = lstr(d, p)
        vc, ic, st = struct.unpack_from('>III', d, p); p += 12
        dt = layout_dtype(layout)
        assert dt.itemsize == st, 'stride mismatch'
        v = np.frombuffer(d, dt, vc, p); p += vc * st           # little-endian payload
        idx = np.frombuffer(d, '<u2', ic, p).astype(np.int64); p += ic * 2
        mat, p = read_material(d, p)
        tris = idx.reshape(-1, 3)
        subs.append(dict(tag=tag, layout=layout, v=normalize_verts(v, tris), tris=tris, material=mat))
    if not bones:                                   # unskinned mesh with no bones: single identity root so exporters work
        bones.append(dict(name='root', parent='', pos=(0.0, 0.0, 0.0), quat=(0.0, 0.0, 0.0, 1.0)))
    return dict(version=ver, hdr=(unk, z, ntri), bounds=bounds, bones=bones,
                subs=subs, end=p, size=len(d))

def read_material(d, p):
    m = {}
    m['shader'], p = lstr(d, p)
    m['name'], p = lstr(d, p)
    p += 5                                                      # 00 00 00 00 01 (UNVERIFIED)
    m['color'] = struct.unpack_from('>4f', d, p); p += 16
    (nt,) = struct.unpack_from('>I', d, p); p += 4
    m['textures'] = {}
    for _ in range(nt):
        k, p = lstr(d, p); v, p = lstr(d, p); m['textures'][k] = v
    (npr,) = struct.unpack_from('>I', d, p); p += 4
    m['params'] = {}
    for _ in range(npr):
        k, p = lstr(d, p)
        (typ,) = struct.unpack_from('<I', d, p); p += 4 + 2
        n = 4 if typ == 7 else 1
        m['params'][k] = struct.unpack_from('<%df' % n, d, p); p += 4 * n
    return m, p


# ----------------------------------------------------------------- .im  (JIRF "IDXM" static/rigid model)
# Chunk = tag(4) | u32 len (INCLUDES the following u32) | u32 ver | body.  Layout found from bogey.im:
#   IDXMINFO(0x44 body: ... f32 x6 bounds @+0x28) | CHNK* | SKEL(BONE*)
#   CHNK = u32 0 | MATL | GEOM
#   MATL = lstr name(len NOT NUL-trimmed, padded) | 16 f32 (UNVERIFIED, [2:6]~diffuse) | u32 ntex | {u32 slot, lstr path, f32}
#   GEOM = u32 4 | u32 0 | f32 ? | u32 vc, ntri, nidx, ntri | u32 0 | lstr boneName |
#          verts (pos3 f32 + uv2 f32, 20B) | u16 tri-list idx | f32 x3 per vert (normals, see _im_tail) | rest ignored
#   BONE = lstr name | pos3 quat4(xyzw) | u32 childCount   (pre-order, same as .kin SKEL; len covers subtree, ignored)
def _im_str(d, p):
    (n,) = struct.unpack_from('<I', d, p)
    return d[p + 4:p + 4 + n].split(b'\0')[0].decode('latin1'), p + 4 + n

def read_im(d):
    if d[:4] != b'JIRF' or d[8:12] != b'IDXM':
        raise ValueError('not JIRF/IDXM')
    bounds = struct.unpack_from('<6f', d, 0x40)  # UNVERIFIED offset/meaning, looks like bbox
    p, raw, bones, tags, attachments = 0x58, [], [], [], []
    while p < len(d):
        if p + 8 > len(d): break                      # trailing padding / truncated chunk header
        tag = d[p:p + 4]; (n,) = struct.unpack_from('<I', d, p + 4); end = p + 8 + n
        tags.append(tag.decode('latin1'))
        if tag == b'CHNK':
            q = p + 12 + 4
            assert d[q:q + 4] == b'MATL'; (ml,) = struct.unpack_from('<I', d, q + 4)
            mat = _read_im_mat(d, q + 12, q + 8 + ml)
            g = q + 8 + ml
            assert d[g:g + 4] == b'GEOM'; (gl,) = struct.unpack_from('<I', d, g + 4)
            raw.append(_read_im_geom(d, g + 12, g + 8 + gl, mat))
        elif tag == b'SKEL':
            q, pend, stack = p + 12, end, []
            while q < pend and d[q:q + 4] == b'BONE':
                q += 12; name, q = _im_str(d, q)
                r = struct.unpack_from('<7f', d, q); q += 28
                (nc,) = struct.unpack_from('<I', d, q); q += 4
                while stack and stack[-1][1] == 0: stack.pop()
                par = bones[stack[-1][0]]['name'] if stack else ''
                if stack: stack[-1][1] -= 1
                stack.append([len(bones), nc])
                bones.append(dict(name=name, parent=par, pos=r[:3], quat=r[3:]))
        elif tag == b'ATCH':
            attachments = _read_im_atch(d, p + 8, min(end, len(d)))
        p = end
    if not attachments:
        # Chunk walk can lose sync on odd files; ATCH is self-describing, so look for it directly (last one wins).
        at = d.rfind(b'ATCH')
        while at > 0 and not attachments:
            try:
                (n,) = struct.unpack_from('<I', d, at + 4)
                attachments = _read_im_atch(d, at + 8, min(at + 8 + n, len(d)))
            except Exception:
                pass
            at = d.rfind(b'ATCH', 0, at) if not attachments else -1
    has_skeleton = bool(bones)
    if not has_skeleton:
        # Static .im with no SKEL chunk: give it a single identity root so every exporter/viewer path still works.
        bones.append(dict(name='root', parent='', pos=(0.0, 0.0, 0.0), quat=(0.0, 0.0, 0.0, 1.0)))
    names = [b['name'] for b in bones]
    _, par_i, rec = bone_tables(dict(bones=bones))
    Wb = world_mats(par_i, rec)       # .im verts are BONE-LOCAL (wheel centred on origin) -> bake to model space
    subs = []
    for g in raw:
        v = np.zeros(len(g['p']), np.dtype([('p', '<f4', 3), ('wi', 'u1', 4), ('wg', '<f4', 4),
                                            ('n', '<f4', 3), ('uv', '<f4', 2)]))
        bi = names.index(g['bone']) if g['bone'] in names else 0
        M = Wb[bi]
        v['p'] = g['p'] @ M[:3, :3].T + M[:3, 3]
        v['n'] = g['n'] @ M[:3, :3].T
        v['uv'] = g['uv']
        v['wi'][:, 0] = bi
        v['wg'][:, 0] = 1.0
        subs.append(dict(tag=b'', layout='im_' + g['bone'], v=v, tris=g['tris'], material=g['mat'],
                         bone=bi, local=(np.array(g['p'], float), np.array(g['n'], float))))
    return dict(version=0, hdr=(0, 0, sum(len(s['tris']) for s in subs)), bounds=bounds,
                bones=bones, subs=subs, end=p, size=len(d), src='im',
                has_skeleton=has_skeleton, chunk_tags=tags, attachments=attachments)

def _read_im_atch(d, p, end):
    """ATCH chunk = u32 ver | u32 count | count x { lstr name | 3x3 rotation (9 f32) | pos3 (3 f32) }.
    These are the 'a.xxx' attachment points (bogeys, cab, smoke...). They are model-space empties: they exist even
    when the model has no skeleton and no animation. Never raises; a damaged chunk just yields what was readable.
    The 3x3 is read as row vectors (Direct3D style) and transposed for the column-vector maths used here (UNVERIFIED;
    all known samples are identity)."""
    out = []
    try:
        ver, n = struct.unpack_from('<II', d, p); q = p + 8
        for _ in range(n):
            if q + 4 > end: break
            name, q = _im_str(d, q)
            if q + 48 > end: break
            f = np.frombuffer(d, '<f4', 12, q).astype(float); q += 48
            R = f[:9].reshape(3, 3).T
            try:
                quat = tuple(float(x) for x in mat_quat(R))
            except Exception:
                quat = (0.0, 0.0, 0.0, 1.0)
            out.append(dict(name=name, pos=tuple(float(x) for x in f[9:12]), quat=quat))
    except Exception:
        pass
    return out

def _attachment_nodes(mesh, nodes, parent_idx=0):
    """Append every .im attachment point as a plain empty node under nodes[parent_idx]; returns how many were added."""
    names = {n.get('name') for n in nodes}
    added = 0
    for a in mesh.get('attachments', []):
        nm = a['name']
        if nm in names:                                   # keep glTF node names unique so importers don't rename them
            k = 2
            while '%s.%d' % (nm, k) in names: k += 1
            nm = '%s.%d' % (nm, k)
        names.add(nm)
        nodes.append(dict(name=nm, translation=list(a['pos']), rotation=list(a['quat']),
                          extras=dict(trainz_attachment=a['name'])))
        nodes[parent_idx].setdefault('children', []).append(len(nodes) - 1)
        added += 1
    return added

def _read_im_mat(d, p, end):
    name, p = _im_str(d, p)
    f = struct.unpack_from('<16f', d, p); p += 64
    (nt,) = struct.unpack_from('<I', d, p); p += 4
    tex = {}
    for _ in range(nt):
        (slot,) = struct.unpack_from('<I', d, p); path, p = _im_str(d, p + 4); p += 4   # trailing f32 (amount?)
        tex['slot%d' % slot] = path.replace('\\', '/').split('/')[-1]
    return dict(shader='im', name=name, color=tuple(f[2:6]), textures=tex, params={'raw16': tuple(f)})

def _read_im_geom(d, p, end, mat):
    _, _, _, vc, nt, ni, _, _ = struct.unpack_from('<IIfIIIII', d, p); p += 32
    bone, p = _im_str(d, p)
    v = np.frombuffer(d, '<f4', vc * 5, p).reshape(vc, 5); p += vc * 20
    idx = np.frombuffer(d, '<u2', ni, p).astype(np.int64); p += ni * 2
    tris = idx.reshape(-1, 3)
    n = _im_tail_normals(d, p, end, vc, v[:, :3], tris)
    return dict(bone=bone, p=v[:, :3], uv=v[:, 3:5], tris=tris, n=n, mat=mat)

def _im_tail_normals(d, p, end, vc, P, tris):
    """Tail after indices is 12*vc bytes + 12*ntri-ish (UNVERIFIED). Use f32x3 at tail start if unit-length, else compute."""
    if end - p >= vc * 12:
        n = np.frombuffer(d, '<f4', vc * 3, p).reshape(vc, 3)
        l = np.linalg.norm(n, axis=1)
        if np.isfinite(l).all() and abs(l.mean() - 1) < 0.05:
            return n
    fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    n = np.zeros_like(P, dtype=float)
    for k in range(3): np.add.at(n, tris[:, k], fn)
    return (n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)).astype('<f4')

def load_mesh(path):
    d = open(path, 'rb').read()
    m = read_im(d) if d[:4] == b'JIRF' else read_mesh(d)
    m['src_dir'] = os.path.dirname(os.path.abspath(path))
    return m

# ----------------------------------------------------------------- kin
def read_kin(d):
    if d[:4] != b'JIRF':
        raise ValueError('not JIRF')
    # ANIMINFO body = lstr source name (len may be 0) | u32 frames | u32 fps | f32 scale
    (alen,) = struct.unpack_from('<I', d, 0x10)
    _, q = _im_str(d, 0x18)
    nframes, fps, scale = struct.unpack_from('<IIf', d, q)
    p = 0x14 + alen
    if d[p:p+4] != b'EVNT':
        # Newer .kin files write every chunk length as 0 and add an extra u32 after the ANIMINFO body,
        # so don't trust lengths: the EVNT chunk follows within a few bytes of the end of the body.
        p = d.find(b'EVNT', q + 12, q + 12 + 32)
        assert p >= 0, 'EVNT chunk not found'
    (nev,) = struct.unpack_from('<I', d, p + 12)
    assert nev == 0, 'events present - layout unknown'
    p += 16
    assert d[p:p+4] == b'SKEL'; p += 12
    names, nchild = [], []
    while d[p:p+4] == b'BONE':
        p += 12
        (n,) = struct.unpack_from('<I', d, p)
        names.append(d[p+4:p+4+n].split(b'\0')[0].decode()); p += 4 + n
        nchild.append(struct.unpack_from('<I', d, p)[0]); p += 4
    # parents from pre-order child counts
    parents, stack = [], []
    for i, c in enumerate(nchild):
        while stack and stack[-1][1] == 0:
            stack.pop()
        parents.append(stack[-1][0] if stack else -1)
        if stack: stack[-1][1] -= 1
        stack.append([i, c])
    nb = len(names)
    frames = []
    k = ((len(d) - p) // max(nframes, 1) - 16) // (4 * nb)     # floats/bone: 10 (pos,quat,scale) or 7 (pos,quat)
    while d[p:p+4] == b'FRAM':
        p += 16
        f = np.frombuffer(d, '<f4', nb * k, p).reshape(nb, k); p += nb * k * 4
        if k == 7: f = np.c_[f, np.ones((nb, 3), '<f4')]
        frames.append(f)
    assert len(frames) == nframes and p == len(d), 'kin tail unexplained (%d/%d)' % (p, len(d))
    return dict(fps=fps, scale=scale, names=names, parents=parents,
                frames=np.array(frames, float))   # (F, B, [pos3 quat4 scale3])


# ----------------------------------------------------------------- .kin -> local TRS (for .im / Max-style kins)
def mat_quat(m):
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = math.sqrt(t + 1) * 2; q = [(m[2, 1]-m[1, 2])/s, (m[0, 2]-m[2, 0])/s, (m[1, 0]-m[0, 1])/s, s/4]
    elif m[0, 0] >= m[1, 1] and m[0, 0] >= m[2, 2]:
        s = math.sqrt(1 + m[0, 0]-m[1, 1]-m[2, 2]) * 2; q = [s/4, (m[0, 1]+m[1, 0])/s, (m[0, 2]+m[2, 0])/s, (m[2, 1]-m[1, 2])/s]
    elif m[1, 1] >= m[2, 2]:
        s = math.sqrt(1 + m[1, 1]-m[0, 0]-m[2, 2]) * 2; q = [(m[0, 1]+m[1, 0])/s, s/4, (m[1, 2]+m[2, 1])/s, (m[0, 2]-m[2, 0])/s]
    else:
        s = math.sqrt(1 + m[2, 2]-m[0, 0]-m[1, 1]) * 2; q = [(m[0, 2]+m[2, 0])/s, (m[1, 2]+m[2, 1])/s, s/4, (m[1, 0]-m[0, 1])/s]
    return np.array(q) / np.linalg.norm(q)

def kin_localize(mesh, kin, space='auto'):
    """The sample .kin (from percy.gmax) stores WORLD-space pos + WORLD rot with conjugated quats (UNVERIFIED: inferred
    from rod/wheel orbit direction). Older sample stored local TRS. space = auto|local|world.
    world -> converts frames to parent-local, sets mesh bones to frame 0 and re-bakes .im verts onto that pose."""
    names, par, rec = bone_tables(mesh)
    F = kin['frames']
    if space == 'auto':
        hasp = [i for i in range(len(par)) if par[i] >= 0]
        d = np.median([np.linalg.norm(F[0][i, :3] - rec[i, :3]) for i in hasp]) if hasp else 0
        space = 'world' if d > 0.01 else 'local'
    kin['space'] = space
    if space == 'local':
        return kin
    out = np.zeros_like(F)
    for fi, fr in enumerate(F):
        W = [trs(r[:3], np.r_[-r[3:6], r[6]]) for r in fr]
        for i in range(len(W)):
            L = W[i] if par[i] < 0 else np.linalg.inv(W[par[i]]) @ W[i]
            out[fi, i, :3] = L[:3, 3]; out[fi, i, 3:7] = mat_quat(L[:3, :3]); out[fi, i, 7:] = 1
    kin['frames'] = out
    for i, b in enumerate(mesh['bones']):                       # rest pose := frame 0
        b['pos'] = tuple(out[0, i, :3]); b['quat'] = tuple(out[0, i, 3:7])
    if mesh.get('src') == 'im':                                 # verts are bone-local -> re-bake on new rest
        _, _, rec = bone_tables(mesh); Wb = world_mats(par, rec)
        for s in mesh['subs']:
            M = Wb[s['bone']]; p, n = s['local']
            s['v']['p'] = p @ M[:3, :3].T + M[:3, 3]; s['v']['n'] = n @ M[:3, :3].T
    return kin


# ----------------------------------------------------------------- animation detection / safe loading
EMBEDDED_ANIM_TAGS = ('ANIM', 'FRAM', 'EVNT', 'KEYF')

def im_animation_report(mesh, kin=None):
    """Answer "does this model have animation?" without raising.
    An .im holds geometry + a bone hierarchy only: keyframes live in a separate .kin. So the report says whether
    the model is *animatable* (has a real skeleton), whether any animation chunk is embedded, and whether the
    supplied .kin (if any) actually fits."""
    real_bones = len(mesh['bones']) if mesh.get('has_skeleton', True) else 0
    tags = mesh.get('chunk_tags', [])
    embedded = any(t in EMBEDDED_ANIM_TAGS for t in tags)
    r = dict(has_skeleton=real_bones > 0, bone_count=real_bones, embedded_animation=embedded,
             animatable=real_bones > 0, kin_ok=None, kin_reason='', frames=0, fps=0)
    if kin is not None:
        ok, why = kin_compatibility(mesh, kin)
        r.update(kin_ok=ok, kin_reason=why, frames=len(kin['frames']), fps=kin['fps'])
    if embedded:
        r['verdict'] = 'This model has animation chunks embedded in the file.'
    elif real_bones == 0:
        r['verdict'] = 'No animation: this model has no skeleton, it is a static mesh.'
    elif kin is None:
        r['verdict'] = ('No embedded animation. The model has %d bone(s) so it CAN be animated, but .im files '
                        'carry no keyframes; those come from a separate .kin file.' % real_bones)
    elif r['kin_ok']:
        r['verdict'] = 'Animated: %d frames @ %d fps from the .kin, matching all %d bones.' % (r['frames'], r['fps'], real_bones)
    else:
        r['verdict'] = 'The .kin does not fit this model (%s); it will be ignored.' % r['kin_reason']
    return r

def kin_compatibility(mesh, kin):
    """(ok, reason) - does this .kin's skeleton match the model's bones?"""
    names, parents, _ = bone_tables(mesh)
    if not mesh.get('has_skeleton', True):
        return False, 'the model has no skeleton'
    if len(kin['frames']) == 0:
        return False, 'the .kin has no frames'
    if kin['names'] != names:
        if len(kin['names']) != len(names):
            return False, '.kin has %d bones, model has %d' % (len(kin['names']), len(names))
        diff = [a for a, b in zip(kin['names'], names) if a != b][:3]
        return False, 'bone names differ (e.g. %s)' % ', '.join(diff)
    if kin['parents'] != parents:
        return False, 'bone hierarchy differs'
    return True, ''

def find_sibling_kin(mesh_path):
    """A .kin sitting next to the model with the same base name, or ''."""
    base = os.path.splitext(mesh_path)[0]
    for ext in ('.kin', '.KIN', '.Kin'):
        if os.path.isfile(base + ext):
            return base + ext
    return ''

def resolve_animation(mesh, kin_path='', mode='auto', mesh_path='', localize=True):
    """Never-raising animation loader shared by the GUI, viewer and CLI.
    mode: 'no'   -> static export, ignore any .kin
          'yes'  -> user says it is animated: use the .kin, but fall back to static (with a note) if it is missing/bad
          'auto' -> use a .kin if one is given (or sits beside the model) and fits, else static
    localize=False skips kin_localize (write_gltf_empty_nodes does its own world->local conversion).
    Returns (kin_or_None, [human-readable notes])."""
    notes = []
    if mode == 'no':
        return None, ['Animation: off, exporting a static model.']
    if not kin_path and mode == 'auto' and mesh_path:
        kin_path = find_sibling_kin(mesh_path)
        if kin_path:
            notes.append('Animation: found matching file %s' % os.path.basename(kin_path))
    if not kin_path:
        notes.append('Animation: no .kin supplied, exporting a static model.' if mode == 'auto' else
                     'Animation: marked "yes" but no .kin was chosen, exporting a static model instead.')
        return None, notes
    try:
        with open(kin_path, 'rb') as fh:
            kin = read_kin(fh.read())
    except Exception as exc:
        why = 'file not found' if isinstance(exc, FileNotFoundError) else 'not a valid or supported .kin file'
        notes.append('Animation: could not read %s (%s), continuing without animation.' % (os.path.basename(kin_path), why))
        return None, notes
    ok, why = kin_compatibility(mesh, kin)
    if not ok:
        notes.append('Animation: %s does not match this model (%s), continuing without animation.'
                     % (os.path.basename(kin_path), why))
        return None, notes
    try:
        if localize:
            kin_localize(mesh, kin)
    except Exception as exc:
        notes.append('Animation: could not apply %s (%s), continuing without animation.' % (os.path.basename(kin_path), exc))
        return None, notes
    notes.append('Animation: %d frames @ %d fps applied.' % (len(kin['frames']), kin['fps']))
    return kin, notes

# ----------------------------------------------------------------- skeleton math
def bone_tables(mesh):
    names = [b['name'] for b in mesh['bones']]
    parents = [names.index(b['parent']) if b['parent'] else -1 for b in mesh['bones']]
    rec = np.array([list(b['pos']) + list(b['quat']) + [1, 1, 1] for b in mesh['bones']], float)
    return names, parents, rec

def world_mats(parents, rec):
    W = []
    for i, r in enumerate(rec):
        L = trs(r[:3], r[3:7], r[7:10])
        W.append(L if parents[i] < 0 else W[parents[i]] @ L)
    return W

def sample(kin, t):
    f = kin['frames']; n = len(f)
    t = t % n if n > 1 else 0
    a = int(math.floor(t)); b = (a + 1) % n; u = t - a
    out = f[a] * (1 - u) + f[b] * u
    for i in range(out.shape[0]):                   # nlerp quats w/ sign fix
        qa, qb = f[a][i, 3:7], f[b][i, 3:7]
        if qa @ qb < 0: qb = -qb
        q = qa * (1 - u) + qb * u
        out[i, 3:7] = q / np.linalg.norm(q)
    return out

def skin_mats(parents, bind_rec, pose_rec):
    Wb, Wp = world_mats(parents, bind_rec), world_mats(parents, pose_rec)
    return [Wp[i] @ np.linalg.inv(Wb[i]) for i in range(len(Wb))]

def skin_verts(v, S):
    p = v['p'].astype(float); n = v['n'].astype(float)
    P = np.zeros_like(p); N = np.zeros_like(n)
    ph = np.c_[p, np.ones(len(p))]
    for k in range(4):
        w = v['wg'][:, k].astype(float)
        if not w.any(): continue
        M = np.array([S[i] for i in v['wi'][:, k]])
        P += w[:, None] * np.einsum('nij,nj->ni', M, ph)[:, :3]
        N += w[:, None] * np.einsum('nij,nj->ni', M[:, :3, :3], n)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    return P, N

# ----------------------------------------------------------------- OBJ
def write_obj(path, mesh, P=None, N=None):
    off = 0
    with open(path, 'w') as f:
        for i, s in enumerate(mesh['subs']):
            v = s['v']
            f.write('o submesh%d\nusemtl %s\n' % (i, s['material']['name']))
            for x in (v['p'] if P is None else P[i]): f.write('v %.6f %.6f %.6f\n' % tuple(x))
            for x in v['uv']: f.write('vt %.6f %.6f\n' % (x[0], 1.0 - x[1]))
            for x in (v['n'] if N is None else N[i]): f.write('vn %.6f %.6f %.6f\n' % tuple(x))
            for a, b, c in s['tris'] + 1 + off:
                f.write('f %d/%d/%d %d/%d/%d %d/%d/%d\n' % (a, a, a, b, b, b, c, c, c))
            off += len(v)

# ----------------------------------------------------------------- GLB
def write_glb(path, mesh, kin=None):
    names, parents, rec = bone_tables(mesh)
    nb = len(names)
    blob = bytearray(); views, accs = [], []

    def add(arr, target=None, typ='SCALAR', ctype=5126, minmax=False):
        arr = np.ascontiguousarray(arr)
        while len(blob) % 4: blob.append(0)
        views.append(dict(buffer=0, byteOffset=len(blob), byteLength=arr.nbytes,
                          **({'target': target} if target else {})))
        blob.extend(arr.tobytes())
        cnt = len(arr)
        a = dict(bufferView=len(views) - 1, componentType=ctype, count=cnt, type=typ)
        if minmax:
            a['min'] = arr.reshape(cnt, -1).min(0).astype(float).tolist()
            a['max'] = arr.reshape(cnt, -1).max(0).astype(float).tolist()
        accs.append(a); return len(accs) - 1

    nodes = [dict(name='ZupToYup', rotation=[-math.sqrt(.5), 0, 0, math.sqrt(.5)])]
    children_of = {i: [] for i in range(nb)}
    for i, p in enumerate(parents):
        if p >= 0: children_of[p].append(i)
    for i in range(nb):
        r = rec[i]
        n = dict(name=names[i], translation=r[:3].tolist(), rotation=r[3:7].tolist())
        if children_of[i]: n['children'] = [1 + c for c in children_of[i]]
        nodes.append(n)
    nodes[0]['children'] = [1 + i for i in range(nb) if parents[i] < 0]

    Wb = world_mats(parents, rec)
    ibm = np.array([np.linalg.inv(m).T.astype('<f4') for m in Wb])   # column-major
    ibm_acc = add(ibm.reshape(nb, 16), typ='MAT4')
    skins = [dict(joints=[1 + i for i in range(nb)], inverseBindMatrices=ibm_acc)]

    meshes, materials = [], []
    for si, s in enumerate(mesh['subs']):
        v = s['v']; m = s['material']
        attrs = dict(POSITION=add(v['p'].astype('<f4'), 34962, 'VEC3', minmax=True),
                     NORMAL=add(v['n'].astype('<f4'), 34962, 'VEC3'),
                     TEXCOORD_0=add(v['uv'].astype('<f4'), 34962, 'VEC2'),
                     JOINTS_0=add(v['wi'].astype('u1'), 34962, 'VEC4', ctype=5121),
                     WEIGHTS_0=add(v['wg'].astype('<f4'), 34962, 'VEC4'))
        ia = add(s['tris'].reshape(-1).astype('<u2'), 34963, 'SCALAR', ctype=5123)
        c = list(m['color'])
        materials.append(dict(name=m['name'], doubleSided=False, extras=dict(
            shader=m['shader'], textures=m['textures'],
            params={k: list(x) for k, x in m['params'].items()}),
            pbrMetallicRoughness=dict(baseColorFactor=c, metallicFactor=1.0, roughnessFactor=0.5)))
        meshes.append(dict(name='submesh%d_%s' % (si, m['name']),
                           primitives=[dict(attributes=attrs, indices=ia, material=si)]))
        nodes.append(dict(name='mesh%d' % si, mesh=si, skin=0))
        nodes[0]['children'].append(len(nodes) - 1)
    _attachment_nodes(mesh, nodes)                      # .im 'a.xxx' attachment points as plain empties

    gl = dict(asset=dict(version='2.0', generator='trainzlib.py'), scene=0,
              scenes=[dict(nodes=[0])], nodes=nodes, meshes=meshes, materials=materials,
              skins=skins)
    if kin:
        assert kin['names'] == names and kin['parents'] == parents, 'mesh/kin skeleton mismatch'
        F = kin['frames']
        times = (np.arange(len(F)) / kin['fps']).astype('<f4')
        tacc = add(times, minmax=True)
        samplers, chans = [], []
        for b in range(nb):
            for chan, sl, typ in (('translation', slice(0, 3), 'VEC3'),
                                  ('rotation', slice(3, 7), 'VEC4'),
                                  ('scale', slice(7, 10), 'VEC3')):
                a = add(F[:, b, sl].astype('<f4'), typ=typ)
                samplers.append(dict(input=tacc, output=a, interpolation='LINEAR'))
                chans.append(dict(sampler=len(samplers) - 1, target=dict(node=1 + b, path=chan)))
        gl['animations'] = [dict(name='anim', samplers=samplers, channels=chans)]
    gl['bufferViews'] = views; gl['accessors'] = accs
    gl['buffers'] = [dict(byteLength=len(blob))]
    js = json.dumps(gl, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    blob += b'\0' * (-len(blob) % 4)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack('<II', len(blob), 0x004E4942)); f.write(blob)



# ----------------------------------------------------------------- textures (.texture -> real image)
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.dds')

def _image_name(tex_name, search_dirs):
    """Trainz names textures 'foo.texture' (a config file, not an image). Return the real image file name:
    an existing foo.<png|jpg|jpeg|tga|bmp|dds> in search_dirs if there is one (also accepts foo.texture.<ext>),
    else foo.png. Names that already are images are kept. Returns (name, found_dir_or_None)."""
    base = os.path.basename(tex_name.replace('\\', '/'))
    stem, ext = os.path.splitext(base)
    if ext.lower() in IMAGE_EXTS:
        cands = [base]
    elif ext.lower() == '.texture' or not ext:
        cands = [stem + e for e in IMAGE_EXTS] + [base + e for e in IMAGE_EXTS]
    else:
        cands = [base]
    for dname in search_dirs:
        if not dname or not os.path.isdir(dname): continue
        try:
            listing = {f.lower(): f for f in os.listdir(dname)}
        except OSError:
            continue
        for c in cands:
            if c.lower() in listing: return listing[c.lower()], dname
    return (cands[0] if ext.lower() in IMAGE_EXTS else stem + '.png'), None

def _diffuse_slot(textures):
    """Which texture is the base colour: a key named diffuse/base/albedo/color, else slot1, else the lowest slot."""
    for k in textures:
        if any(w in k.lower() for w in ('diffuse', 'albedo', 'base', 'color', 'colour')): return k
    keys = sorted(textures, key=lambda k: int(re.sub(r'\D', '', k) or 0))
    return 'slot1' if 'slot1' in textures else (keys[0] if keys else None)


def _rigid_parts(mesh, s, Wb):
    """Split one submesh into rigid parts, one per bone, as (bone, local_p, local_n, uv, tris).
    .im submeshes already belong to one bone and keep their bone-local verts. .trainzmesh verts are skinned in model
    space, so each triangle goes to the bone with the highest weight at its first vertex and the verts are moved into
    that bone's local space, so a plain node hierarchy can carry them."""
    v = s['v']
    if 'local' in s:
        lp, ln = s['local']
        return [(int(s.get('bone', 0)), lp, ln, v['uv'], s['tris'])]
    wg = v['wg'].astype(float)
    vb = v['wi'][np.arange(len(v)), wg.argmax(1)].astype(int)
    vb = np.where(vb < len(Wb), vb, 0)
    tris = np.asarray(s['tris'])
    tb = vb[tris[:, 0]] if len(tris) else np.zeros(0, int)
    parts = []
    for b in sorted(set(tb.tolist())) or [0]:
        t = tris[tb == b] if len(tris) else tris
        used = np.unique(t) if len(t) else np.zeros(0, int)
        remap = np.zeros(len(v), np.int64); remap[used] = np.arange(len(used))
        inv = np.linalg.inv(Wb[b])
        p = v['p'][used].astype(float) @ inv[:3, :3].T + inv[:3, 3]
        n = v['n'][used].astype(float) @ inv[:3, :3].T
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        parts.append((int(b), p, n, v['uv'][used], remap[t]))
    return parts

# ----------------------------------------------------------------- glTF (.gltf + .bin), empty-node hierarchy
def write_gltf_empty_nodes(path, mesh, kin=None):
    """Export an original .im as glTF with ordinary animated transform nodes, not a skin.

    The .im reader retains each submesh's original bone-local positions in s['local'].
    Those positions are exported directly and the mesh node is parented under that
    named hierarchy node. This is intended for rigidly bone-attached .im submeshes.
    """
    names, parents, rec = bone_tables(mesh)
    nb = len(names)
    Wb = world_mats(parents, rec)
    if kin and (kin['names'] != names or kin['parents'] != parents):
        raise ValueError("The .kin skeleton does not match the model hierarchy.")

    path = os.path.abspath(path)
    root, _ = os.path.splitext(path)
    bin_name = os.path.basename(root) + ".bin"
    bin_path = os.path.join(os.path.dirname(path), bin_name)
    blob = bytearray()
    views, accs = [], []

    def add(arr, target=None, typ='SCALAR', ctype=5126, minmax=False):
        arr = np.ascontiguousarray(arr)
        while len(blob) % 4:
            blob.append(0)
        view = dict(buffer=0, byteOffset=len(blob), byteLength=arr.nbytes)
        if target:
            view['target'] = target
        views.append(view)
        blob.extend(arr.tobytes())
        cnt = len(arr)
        a = dict(bufferView=len(views)-1, componentType=ctype, count=cnt, type=typ)
        if minmax:
            flat = arr.reshape(cnt, -1)
            a['min'] = flat.min(0).astype(float).tolist()
            a['max'] = flat.max(0).astype(float).tolist()
        accs.append(a)
        return len(accs)-1

    nodes = [dict(name='ZupToYup', rotation=[-math.sqrt(.5), 0, 0, math.sqrt(.5)])]
    children_of = {i: [] for i in range(nb)}
    for i, p in enumerate(parents):
        if p >= 0:
            children_of[p].append(i)
    for i, r in enumerate(rec):
        node = dict(name=names[i], translation=r[:3].tolist(), rotation=r[3:7].tolist())
        if children_of[i]:
            node['children'] = [1+c for c in children_of[i]]
        nodes.append(node)
    nodes[0]['children'] = [1+i for i in range(nb) if parents[i] < 0]

    meshes, materials = [], []
    images, gtextures = [], []                          # glTF images: real image files, never '.texture'
    img_index = {}
    search_dirs = [mesh.get('src_dir', ''), os.path.dirname(path)]
    for si, s in enumerate(mesh['subs']):
        m = s['material']
        c = list(m['color'])
        tex_extras, base_tex = {}, None
        for slot, tname in m['textures'].items():
            iname, found = _image_name(tname, search_dirs)
            tex_extras[slot] = iname
            if found and os.path.abspath(found) != os.path.dirname(path):
                try:                                    # put a copy beside the .gltf so the relative uri resolves
                    shutil.copyfile(os.path.join(found, iname), os.path.join(os.path.dirname(path), iname))
                except OSError:
                    pass
            if slot == _diffuse_slot(m['textures']):
                if iname not in img_index:
                    images.append(dict(uri=urllib.parse.quote(iname), name=os.path.splitext(iname)[0]))
                    gtextures.append(dict(source=len(images) - 1))
                    img_index[iname] = len(gtextures) - 1
                base_tex = img_index[iname]
        if base_tex is not None:
            c = [1.0, 1.0, 1.0, c[3]]                   # textured: don't tint/darken the image with the material colour
        pbr = dict(baseColorFactor=c, metallicFactor=0.0 if base_tex is not None else 1.0, roughnessFactor=0.5)
        if base_tex is not None:
            pbr['baseColorTexture'] = dict(index=base_tex)
        materials.append(dict(name=m['name'], doubleSided=False,
            extras=dict(shader=m['shader'], textures=tex_extras,
                        params={k:list(x) for k,x in m['params'].items()}),
            pbrMetallicRoughness=pbr))
        parts = _rigid_parts(mesh, s, Wb)
        for pi, (bone_i, lp, ln, luv, ltris) in enumerate(parts):
            attrs = dict(
                POSITION=add(np.asarray(lp, dtype='<f4'), 34962, 'VEC3', minmax=True),
                NORMAL=add(np.asarray(ln, dtype='<f4'), 34962, 'VEC3'),
                TEXCOORD_0=add(np.asarray(luv, dtype='<f4'), 34962, 'VEC2'))
            ia = add(np.asarray(ltris).reshape(-1).astype('<u2'), 34963, 'SCALAR', ctype=5123)
            suffix = '' if len(parts) == 1 else '_' + names[bone_i]
            meshes.append(dict(name='submesh%d%s_%s' % (si, suffix, m['name']),
                               primitives=[dict(attributes=attrs, indices=ia, material=si)]))
            mesh_node_idx = len(nodes)
            nodes.append(dict(name='mesh%d%s' % (si, suffix), mesh=len(meshes) - 1))
            nodes[1 + bone_i].setdefault('children', []).append(mesh_node_idx)
    _attachment_nodes(mesh, nodes)                      # .im 'a.xxx' attachment points, exported even for static models

    gl = dict(asset=dict(version='2.0', generator='trainzlib.py (empty-node export)'),
              scene=0, scenes=[dict(nodes=[0])], nodes=nodes, meshes=meshes, materials=materials)
    if images:
        gl['images'] = images; gl['textures'] = gtextures
    if kin:
        # .kin files for this .im can store WORLD-space transforms (including
        # world-space positions for child nodes). glTF animation channels are
        # always parent-local, so convert the full animation to local TRS.
        F = np.asarray(kin['frames'], dtype=float).copy()
        hasp = [i for i, parent in enumerate(parents) if parent >= 0]
        d = np.median([np.linalg.norm(F[0, i, :3] - rec[i, :3]) for i in hasp]) if hasp else 0.0
        if d > 0.01:
            local_frames = np.zeros_like(F)
            for fi, fr in enumerate(F):
                world = [trs(r[:3], np.r_[-r[3:6], r[6]], r[7:10]) for r in fr]
                for bi, parent in enumerate(parents):
                    local = world[bi] if parent < 0 else np.linalg.inv(world[parent]) @ world[bi]
                    local_frames[fi, bi, :3] = local[:3, 3]
                    local_frames[fi, bi, 3:7] = mat_quat(local[:3, :3])
                    local_frames[fi, bi, 7:10] = 1.0
            F = local_frames
        times = (np.arange(len(F)) / max(1, kin['fps'])).astype('<f4')
        tacc = add(times, minmax=True)
        samplers, chans = [], []
        for b in range(nb):
            for chan, sl, typ in (('translation', slice(0,3), 'VEC3'),
                                  ('rotation', slice(3,7), 'VEC4'),
                                  ('scale', slice(7,10), 'VEC3')):
                out_acc = add(F[:, b, sl].astype('<f4'), typ=typ)
                samplers.append(dict(input=tacc, output=out_acc, interpolation='LINEAR'))
                chans.append(dict(sampler=len(samplers)-1, target=dict(node=1+b, path=chan)))
        gl['animations'] = [dict(name='anim', samplers=samplers, channels=chans)]

    gl['bufferViews'] = views
    gl['accessors'] = accs
    gl['buffers'] = [dict(uri=bin_name, byteLength=len(blob))]
    js = json.dumps(gl, separators=(',', ':')).encode('utf-8')
    with open(bin_path, 'wb') as f:
        f.write(blob)
    with open(path, 'wb') as f:
        f.write(js)

# ----------------------------------------------------------------- CLI
def info(mesh, kin=None):
    print('tzMF v%d  tris(header)=%d  bounds=%s' % (mesh['version'], mesh['hdr'][2],
          np.round(mesh['bounds'], 3).tolist()))
    print('parsed to byte %d of %d' % (mesh['end'], mesh['size']))
    for i, b in enumerate(mesh['bones']):
        print('  bone %d %-12s parent=%-10s pos=%s' % (i, b['name'], b['parent'] or '-', np.round(b['pos'], 4).tolist()))
    for i, s in enumerate(mesh['subs']):
        v = s['v']; m = s['material']
        print('submesh %d %s verts=%d tris=%d tag=%s mat=%s/%s' % (i, s['layout'], len(v),
              len(s['tris']), s['tag'].hex(), m['shader'], m['name']))
        print('   skinned to', sorted(set(v['wi'][v['wg'] > 0].tolist())), ' textures', m['textures'])
    if kin:
        print('kin: %d frames @%d fps, bones=%s parents=%s' % (len(kin['frames']), kin['fps'], kin['names'], kin['parents']))
    for a in mesh.get('attachments', []):
        print('  attachment %-14s pos=%s' % (a['name'], np.round(a['pos'], 4).tolist()))
    if mesh.get('src') == 'im':
        print('has animation?  ' + im_animation_report(mesh, kin)['verdict'])

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['info', 'obj', 'glb', 'gltf'])
    ap.add_argument('mesh'); ap.add_argument('out', nargs='?')
    ap.add_argument('--kin'); ap.add_argument('--frame', type=float)
    ap.add_argument('--anim', choices=['auto', 'yes', 'no'], default='auto', help='does the .im have animation? (default auto)')
    a = ap.parse_args()
    mesh = load_mesh(a.mesh)
    kin, notes = resolve_animation(mesh, a.kin or '', a.anim, a.mesh)
    for n in notes: print(n)
    if a.cmd == 'info':
        info(mesh, kin)
    elif a.cmd == 'obj':
        P = N = None
        if kin and a.frame is not None:
            names, par, rec = bone_tables(mesh)
            S = skin_mats(par, rec, sample(kin, a.frame))
            P, N = zip(*[skin_verts(s['v'], S) for s in mesh['subs']])
        write_obj(a.out, mesh, P, N)
    elif a.cmd == 'glb':
        write_glb(a.out, mesh, kin)
    else:
        write_gltf_empty_nodes(a.out, mesh, kin)
    print('ok')
