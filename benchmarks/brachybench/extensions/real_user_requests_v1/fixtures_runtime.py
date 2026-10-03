"""Complete synthetic fixtures, real raster/mask assets and parseable PDFs.

This is a shared *decision environment*, not a clinical dose/segmentation engine
or a replacement for BrachyBot's browser. No patient filesystem is accessed.
"""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path


ORGAN_IDS = (
 "spinal_cord brain esophagus trachea thyroid_gland skull "
 "common_carotid_artery_left common_carotid_artery_right "
 "subclavian_artery_left subclavian_artery_right brachiocephalic_trunk "
 "brachiocephalic_vein_left brachiocephalic_vein_right superior_vena_cava aorta "
 "vertebrae_C1 vertebrae_C2 vertebrae_C3 vertebrae_C4 vertebrae_C5 vertebrae_C6 vertebrae_C7 "
 "vertebrae_T1 vertebrae_T2 vertebrae_T3 vertebrae_T4 vertebrae_T5 vertebrae_T6 "
 "clavicula_left clavicula_right scapula_left scapula_right humerus_left "
 "autochthon_left autochthon_right lung_upper_lobe_left lung_upper_lobe_right "
 "lung_lower_lobe_left lung_lower_lobe_right sternum costal_cartilages "
 "rib_left_1 rib_left_2 rib_left_3 rib_left_4 rib_left_5 rib_left_6 "
 "rib_right_1 rib_right_2 rib_right_3 rib_right_4 rib_right_5 rib_right_6"
).split()


def digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
                             separators=(",",":"),allow_nan=False).encode()).hexdigest()


def camera(name="camera-original"):
    return {"name":name,"position_mm":[0,0,100],"target_mm":[0,0,0],"up":[0,1,0],
            "vertical_span_mm":160 if name == "far-overview" else 60,
            "projection":"orthographic","width":160,"height":160}


def materialize(case):
    state = deepcopy(case["initial_state"])
    state["synthetic"] = True
    state.setdefault("tenant_id","tenant-A")
    state.setdefault("prescription_Gy",120.0)
    state.setdefault("patient_crosshair_mm",[0,0,0])
    v = state.setdefault("viewer",{})
    if not isinstance(v.get("camera"),dict):
        v["camera"] = camera(v.get("camera","camera-original"))
    state["case_B_camera"] = camera("case-B-default")
    objs = state["objects"]
    if case["id"]=="RUR-24-002":
        objs.update({"oar-cord":{"label":"Synthetic spinal cord","type":"OAR","visible":True,
                                "position_mm":[-19,0,-5],"radius_mm":5,"color":"blue","opacity":.5},
                     "oar-brain":{"label":"Synthetic nearby structure","type":"OAR","visible":True,
                                 "position_mm":[0,19,-5],"radius_mm":5,"color":"green","opacity":.5}})
    for group,members in state.get("group_members",{}).items():
        for target in members:
            objs.setdefault(target,{"label":target,"type":group,"visible":True})
    # Geometry belongs to the synthetic world, not the answer key.
    for i,(target,item) in enumerate(objs.items()):
        item.setdefault("label",target)
        item.setdefault("visible",True)
        item.setdefault("opacity",1.)
        item.setdefault("color","red" if item.get("type")=="CTV" else "cyan")
        item.setdefault("position_mm",[0,0,20] if item.get("type")=="guide" else [0,0,0] if item.get("type") in ("CTV","seed") else [4,0,0])
        item.setdefault("radius_mm",12 if item.get("type")=="CTV" else .4 if item.get("type") in ("seed","needle") else 3)
        if item.get("type")=="guide":
            for key, value in dict(version=1, position_mm=[0,0,20], shape="plate", half_size_mm=[16,16]).items():
                item.setdefault(key, value)
        elif item.get("type")=="needle":
            center=item["position_mm"]
            item.setdefault("endpoints_mm",[[center[j]+v[j] for j in range(3)] for v in ([-15,-8,-5],[15,8,5])])
    state.setdefault("report",{"body_language":state["language"],"captions_language":state["language"]})
    localize_report(state["report"])
    if case["id"]=="RUR-24-001":
        # Materialize the declared occlusion into an actual opaque surface.
        objs["guide-A"]["opacity"]=1.
    state.setdefault("edit_log",[])
    if case["id"] == "RUR-06-001":
        objs["needle-A"]["position_mm"]=[4,0,0]
        objs["seed-A"]["position_mm"]=[5,0,0]
        for edit in state["edit_log"]:
            edit.update(case_id=state["case_id"],session_id=state["session_id"],
                        planning_id=state["planning_id"],before_position_mm=[0,0,0],consumed=False)
    if case["id"] == "RUR-19-002":
        state["edit_log"]=[{"id":"cp-7","target":"seed-A","before_position_mm":[0,0,0],
                            "to":7,"consumed":False,"case_id":"case-A","session_id":"session-A","planning_id":"plan-A"}]
    # A nonempty explicitly versioned 53-row table; contains exact zero and
    # genuinely missing values. No row_count flag substitutes for records.
    if case["id"] == "RUR-40-001":
        state["metrics"]["OAR"]={name:{"D2cc_Gy":None if i==2 else
                7.3 if i==0 else 4.8 if i==1 else 0. if i%4==0 else round(3/(i+1),4),
                "valid_for_revision":state["geometry_revision"],"synthetic":True}
                for i,name in enumerate(ORGAN_IDS)}
        state["organ_table"]={"synthetic":True,"rows":deepcopy(state["metrics"]["OAR"])}
    records={}
    for kind,status in state["artifacts"].items():
        if status != "absent":
            records[kind]={"id":f"initial-{kind}-{state['case_id']}","case_id":state["case_id"],
                           "planning_id":state["planning_id"],"revision":max(0,state["geometry_revision"]-(status!="current")),
                           "status":status,"source":"fixture", "synthetic":True}
    state["artifact_records"]=records
    for row in state.get("metrics",{}).get("OAR",{}).values():
        row.setdefault("valid_for_revision",state["geometry_revision"])
    state["tree_state"]=deepcopy(objs)
    state["render_state"]=deepcopy(objs)
    state["saved_state"]=deepcopy(objs)
    state["history"] += [{"user":s["user"],"assistant":s["assistant"],"origin":"prior_fixture"}
                          for s in case["steps"] if s["kind"]=="prior_exchange_fixture"]
    if case["id"]=="RUR-37-001":
        state["source_user_turns"]={"u-original":{"case_id":state["case_id"],"planning_id":state["planning_id"],
                    "role":"user","text":"只更新过期报告，导板和针、粒子几何不要动。","exclusions":["guide","geometry"]}}
    state["provider_records"]=[]
    state["request"]={"status":"idle","send_enabled":True,"final_count":0}
    state["attachments"]=[]
    state["available_captures"]=[]
    state["downloads"]=[]
    state["available_downloads"]=[]
    state["protocol_receipts"]=[]
    return state


def localize_report(report):
    zh=report["body_language"]=="zh"
    report["body_text"]="合成计划报告（非临床计划）" if zh else "Synthetic plan report (not a clinical plan)"
    zh=report["captions_language"]=="zh"
    report["captions"]=["全局粒子植入计划","靶区粒子分布近景"] if zh else ["Global seed implant plan","CTV seed distribution close-up"]


COLORS={"red":(220,45,60),"cyan":(20,210,200),"blue":(45,90,225),"green":(30,210,80)}


def _cross(a,b):
    return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def _unit(v):
    n=math.sqrt(sum(x*x for x in v))
    if not math.isfinite(n) or n < 1e-10:
        raise ValueError("degenerate camera")
    return [x/n for x in v]


def render(state, target, *, width=None):
    """Independent orthographic primitive raster + depth/visible-target mask.

    The mask comes from surface visibility, NOT a projected target bbox. The
    clinical anatomy is deliberately not emulated. Viewer camera remains exact.
    """
    cam=state["viewer"]["camera"]
    w=width or cam["width"]; h=width or cam["height"]
    if not (16<=w<=512 and 16<=h<=512 and 0<cam["vertical_span_mm"]<10000):
        raise ValueError("invalid render dimensions/framing")
    eye=cam["position_mm"]; aim=cam["target_mm"]
    front=_unit([eye[i]-aim[i] for i in range(3)])
    right=_unit(_cross(cam["up"],front)); up=_cross(front,right)
    objects=[(k,v) for k,v in state["objects"].items() if v.get("visible") and v.get("opacity",1)>0]
    rgb=bytearray(w*h*3); mask=bytearray(w*h); full=bytearray(w*h)
    for y in range(h):
        for x in range(w):
            rx=((x+.5)/w-.5)*cam["vertical_span_mm"]*w/h
            ry=(.5-(y+.5)/h)*cam["vertical_span_mm"]
            surfaces=[]
            for oid,obj in objects:
                rel=[obj["position_mm"][i]-aim[i] for i in range(3)]
                ox=sum(rel[i]*right[i] for i in range(3)); oy=sum(rel[i]*up[i] for i in range(3)); z=sum(rel[i]*front[i] for i in range(3))
                dx=rx-ox; dy=ry-oy
                if obj.get("type")=="needle" and obj.get("endpoints_mm"):
                    uv=[]
                    for endpoint in obj["endpoints_mm"]:
                        q=[endpoint[i]-aim[i] for i in range(3)]
                        uv.append([sum(q[i]*axis[i] for i in range(3)) for axis in (right,up,front)])
                    aa,bb=uv; vx=bb[0]-aa[0]; vy=bb[1]-aa[1]
                    t=max(0,min(1,((rx-aa[0])*vx+(ry-aa[1])*vy)/max(1e-12,vx*vx+vy*vy)))
                    d2=(rx-aa[0]-t*vx)**2+(ry-aa[1]-t*vy)**2
                    r=obj["radius_mm"]; hit=d2<=r*r
                    z=aa[2]+t*(bb[2]-aa[2])+math.sqrt(max(0,r*r-d2))
                elif obj.get("shape")=="plate":
                    a,b=obj["half_size_mm"]; hit=abs(dx)<=a and abs(dy)<=b
                else:
                    r=obj["radius_mm"]; hit=dx*dx+dy*dy<=r*r
                    if hit: z+=math.sqrt(max(0,r*r-dx*dx-dy*dy))
                if hit:
                    surfaces.append((z,oid,obj))
                    if oid==target: full[y*w+x]=255
            surfaces.sort(key=lambda s:s[0])
            accum=[0.,0.,0.]; transmission=1.
            for z,oid,obj in reversed(surfaces):
                alpha=obj.get("opacity",1.)
                if oid==target and transmission*alpha>=.15: mask[y*w+x]=255
                c=COLORS.get(obj.get("color"),(160,160,160))
                for j in range(3): accum[j]+=transmission*alpha*c[j]
                transmission*=1-alpha
            rgb[3*(y*w+x):3*(y*w+x)+3]=bytes(round(min(255,v)) for v in accum)
    points=[(i%w,i//w) for i,v in enumerate(mask) if v]
    bounds=[min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)] if points else None
    return {"ppm":f"P6\n{w} {h}\n255\n".encode()+rgb,
            "pgm":f"P5\n{w} {h}\n255\n".encode()+mask,"visible_mask":bytes(mask),
            "width":w,"height":h,"target_pixels":len(points),"full_pixels":sum(bool(x) for x in full),
            "bbox":bounds,"clipped":bool(points and any(x in (0,w-1) or y in (0,h-1) for x,y in points))}


def annotate_ppm(data,width,height,anchor,label):
    if not anchor or len(anchor)!=2 or any(type(v)!=int for v in anchor): return data
    if not (0<=anchor[0]<width and 0<=anchor[1]<height): return data
    from PIL import Image, ImageDraw
    head=f"P6\n{width} {height}\n255\n".encode()
    image=Image.frombytes("RGB",(width,height),data[len(head):]); draw=ImageDraw.Draw(image)
    start=(max(4,anchor[0]-25),max(15,anchor[1]-25))
    draw.line([start,tuple(anchor)],fill=(120,255,0),width=2)
    draw.ellipse([anchor[0]-1,anchor[1]-1,anchor[0]+1,anchor[1]+1],fill=(120,255,0))
    draw.text((3,2),label,fill=(120,255,0))
    return head+image.tobytes()


def render_tree(state,target):
    from PIL import Image,ImageDraw
    objects=state["objects"]; ids=list(objects)
    width=360; height=max(80,28+22*len(ids))
    image=Image.new("RGB",(width,height),(18,24,40)); draw=ImageDraw.Draw(image)
    draw.text((5,3),"Synthetic Data Tree",fill=(220,220,220))
    for i,oid in enumerate(ids):
        obj=objects[oid]; y=25+22*i
        draw.ellipse((4,y+3,12,y+11),fill=COLORS.get(obj.get("color"),(160,160,160)))
        draw.text((18,y),f"{obj['label']} [{oid}] {'visible' if obj['visible'] else 'hidden'}",fill=(230,230,230))
    index=ids.index(target); y=25+22*index; bbox=[16,y,350,y+17]
    mask=bytearray(width*height)
    for yy in range(y,y+18):
        for xx in range(16,351): mask[yy*width+xx]=255
    pixels=sum(bool(x) for x in mask)
    return {"ppm":f"P6\n{width} {height}\n255\n".encode()+image.tobytes(),
            "pgm":f"P5\n{width} {height}\n255\n".encode()+mask,"visible_mask":bytes(mask),
            "width":width,"height":height,"bbox":bbox,"target_pixels":pixels,"full_pixels":pixels,"clipped":False}


def pdf_bytes(state, *, figures=()):
    """Valid uncompressed PDF with xref and independently extractable scope.

    PDF language assertions use UTF-16BE metadata fields; a PDF parser is still
    required by the evaluator. Header/EOF matching is intentionally insufficient.
    """
    text=f"Synthetic decision fixture | Case {state['case_id']} | Plan {state['planning_id']} | Revision {state['geometry_revision']} | Prescription {state['prescription_Gy']} Gy"
    escaped=text.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
    stream=f"BT /F1 11 Tf 36 760 Td ({escaped}) Tj ET\n".encode()
    # Embed actual raster figures rather than metadata-only image references.
    resources=" ".join(f"/I{i} {7+i} 0 R" for i in range(len(figures)))
    for i,figure in enumerate(figures):
        stream+=f"q 240 0 0 240 {36+260*(i%2)} {400-260*(i//2)} cm /I{i} Do Q\n".encode()
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
             ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> /XObject << "+resources+" >> >> /Contents 5 0 R >>").encode(),
             b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
             b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"endstream"]
    metadata={"CaseID":state["case_id"],"PlanID":state["planning_id"] or "none","Revision":str(state["geometry_revision"]),
              "BodyLanguage":state["report"]["body_language"],"CaptionLanguage":state["report"]["captions_language"],
              "Synthetic":"true","FigureIDs":",".join(f["id"] for f in figures)}
    objects.append(("<< "+" ".join(f"/{k} <{('FEFF'+v.encode('utf-16be').hex()).upper()}>" for k,v in metadata.items())+" >>").encode())
    for f in figures:
        head=f"P6\n{f['width']} {f['height']}\n255\n".encode()
        pixels=f["data"][len(head):]
        if len(pixels)!=f["width"]*f["height"]*3: raise ValueError("invalid PDF figure raster")
        objects.append(f"<< /Type /XObject /Subtype /Image /Width {f['width']} /Height {f['height']} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length {len(pixels)} >>\nstream\n".encode()+pixels+b"\nendstream")
    result=bytearray(b"%PDF-1.4\n%synthetic\n"); offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(result)); result+=f"{i} 0 obj\n".encode()+obj+b"\nendobj\n"
    xref=len(result); result+=f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]: result+=f"{offset:010d} 00000 n \n".encode()
    result+=f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(result)


def write_assets(state, root):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    pdf=pdf_bytes(state); (root/"initial_report.pdf").write_bytes(pdf)
    written={"initial_report.pdf":sha256(pdf).hexdigest()}
    for target in state["objects"]:
        image=render(state,target)
        for ext,key in (("ppm","ppm"),("pgm","pgm")):
            name=f"{target}.{ext}"; (root/name).write_bytes(image[key]); written[name]=sha256(image[key]).hexdigest()
    return written
