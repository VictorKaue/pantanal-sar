"""QC: NISAR open water (2026-07-17, HH < -16.75 dB, 20 m) vs OPERA DSWx-HLS.

Whole-AOI agreement (F1, kappa) and the dark south-west patches (possible burn/smooth soil).
Needs data/processed/nisar/2026-07-17_HHHH_20m_aoi.tif, the local 07-17 .h5 (for HV) and the
DSWx cache from `cli fetch-opera`. Output: printed table + data/qc/nisar_sw_patches_vs_dswx_2026-07-17.png
Run: python scripts/qc_nisar_vs_dswx.py
"""
import glob, h5py, numpy as np, rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.transform import Affine, xy
from pantanal_sar import change, opera, water_series as ws
from pantanal_sar.gcov import read_subset
from pantanal_sar.config import load_config
cfg=load_config(); bb=cfg["bbox"]
with rasterio.open("data/processed/nisar/2026-07-17_HHHH_20m_aoi.tif") as r:
    hh=r.read(1); T=r.transform; crs=r.crs
f=h5py.File(glob.glob("data/raw/nisar/*20260717T*.h5")[0])
hv=read_subset(f,bb,"frequencyA",("HVHV",))[0]["HVHV"]
hhdb=change.to_db(change.lee_filter(hh,5)); hvdb=change.to_db(change.lee_filter(hv,5))
ins=ws.bbox_mask(hh.shape,T,crs,bb)
wat=change.open_water(np.where(ins,hhdb,np.nan),-16.75)
valid=np.isfinite(hhdb)&ins
# OPERA grid
left,top,nc,nr=opera.aoi_grid(bb); OT=Affine(30,0,left,0,-30,top)
def dswx(day):
    fs=sorted(glob.glob(f"data/raw/opera_dswx/*_T?????_{day}T*.npz"))
    return opera.composite([np.load(x)["wtr"] for x in fs]), ["_".join(x.split("/")[-1].split("_")[3:5])[:22]+"_"+x.split("/")[-1].split("_")[6] for x in fs]
src=np.where(valid, wat.astype("uint8"), 255).astype("uint8")
nis=np.full((nr,nc),255,"uint8")
reproject(src,nis,src_transform=T,src_crs=crs,dst_transform=OT,dst_crs="EPSG:32621",src_nodata=255,dst_nodata=255,resampling=Resampling.mode)
# SW patch window, figure 40 m coords -> 20 m rows/cols
r0,r1,c0,c1=4600,4900,1400,1800
(xa,xb),(ya,yb)=xy(T,[r0,r1],[c0,c1])
pb=transform_bounds(crs,"EPSG:32621",min(xa,xb),min(ya,yb),max(xa,xb),max(ya,yb))
lonlat=transform_bounds(crs,"EPSG:4326",min(xa,xb),min(ya,yb),max(xa,xb),max(ya,yb))
print("patch lon/lat", [round(v,3) for v in lonlat])
oc0=int((pb[0]-left)/30); oc1=int((pb[2]-left)/30); or0=int((top-pb[3])/30); or1=int((top-pb[1])/30)
pw=wat[r0:r1,c0:c1]
print(f"patch NISAR: agua {pw.sum()*4e-4:.1f} km2; HH agua med {np.nanmedian(hhdb[r0:r1,c0:c1][pw]):.1f} dB, HV agua med {np.nanmedian(hvdb[r0:r1,c0:c1][pw]):.1f} dB, HH-HV {np.nanmedian((hhdb-hvdb)[r0:r1,c0:c1][pw]):.1f}")
# reference: big southern lake (known water): rows 5300-5550, cols 2300-3000
lw=wat[5300:5550,2300:3000]
print(f"lagoa sul: HH {np.nanmedian(hhdb[5300:5550,2300:3000][lw]):.1f} HV {np.nanmedian(hvdb[5300:5550,2300:3000][lw]):.1f} HH-HV {np.nanmedian((hhdb-hvdb)[5300:5550,2300:3000][lw]):.1f}")
def stats(a,b,lab):
    m=(a!=255)&np.isin(b,(0,1,2))
    A=a[m]==1; B1=b[m]==1; B12=np.isin(b[m],(1,2))
    out=[]
    for name,B in (("classe1",B1),("classe1+2",B12)):
        tp=(A&B).sum(); fp=(A&~B).sum(); fn=(~A&B).sum(); tn=(~A&~B).sum(); n=tp+fp+fn+tn
        po=(tp+tn)/n; pe=((tp+fp)*(tp+fn)+(fn+tn)*(fp+tn))/n**2
        out.append(f"{name}: F1 {2*tp/(2*tp+fp+fn):.2f} kappa {(po-pe)/(1-pe):.2f}")
    return f"{lab}: px claros comuns {m.sum()}, " + "; ".join(out)
for day in ("20260717","20260719"):
    d,names=dswx(day)
    print(day, names, "claro AOI", round(np.isin(d,(0,1,2)).mean(),3))
    print("  ",stats(nis,d,"AOI inteiro"))
    pd=d[or0:or1,oc0:oc1]; pn=nis[or0:or1,oc0:oc1]
    sel=(pn==1)
    vals,cnt=np.unique(pd[sel],return_counts=True)
    print("   patch: classes DSWx onde NISAR=agua:", dict(zip(vals.tolist(),cnt.tolist())))
    vals,cnt=np.unique(pd,return_counts=True); print("   patch: classes DSWx (todo recorte):", dict(zip(vals.tolist(),cnt.tolist())))
    

print("opera patch window", or0,or1,oc0,oc1)
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
d19=dswx("20260719")[0]; d17=dswx("20260717")[0]
def col(a):
    o=np.full(a.shape+(3,),0.85); o[a==0]=(0.95,0.93,0.85); o[a==1]=(0.1,0.3,0.8); o[a==2]=(0.5,0.75,1); o[a==253]=(0.6,0.6,0.6); return o
pad=60
R=slice(max(or0-pad,0),or1+pad); C=slice(max(oc0-pad,0),oc1+pad)
fig,ax=plt.subplots(1,4,figsize=(18,5))
hr=slice(r0-90,r1+90); hc=slice(c0-90,c1+90)
ax[0].imshow(hhdb[hr,hc],vmin=-22,vmax=0,cmap="gray"); ax[0].contour(wat[hr,hc],[0.5],colors="r",linewidths=0.6); ax[0].set_title("NISAR HH dB 17/07 (vermelho: agua < -16,75)")
ax[1].imshow(hvdb[hr,hc],vmin=-32,vmax=-10,cmap="gray"); ax[1].set_title("NISAR HV dB 17/07")
ax[2].imshow(col(d17[R,C])); ax[2].set_title("DSWx-HLS 17/07 (S2B)")
ax[3].imshow(col(d19[R,C])); ax[3].set_title("DSWx-HLS 19/07 (L9+S2C)\nazul escuro: agua; claro: parcial; cinza: nuvem")
for a in ax: a.set_xticks([]); a.set_yticks([])
fig.suptitle(f"Manchas escuras do sudoeste, lon {lonlat[0]:.2f} a {lonlat[2]:.2f}, lat {lonlat[1]:.2f} a {lonlat[3]:.2f}")
fig.tight_layout(); fig.savefig("data/qc/nisar_sw_patches_vs_dswx_2026-07-17.png",dpi=90)
