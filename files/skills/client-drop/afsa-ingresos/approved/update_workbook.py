"""Update only the authorized business-date row of AFSA Ingresos (Excel).
Usage: python update_workbook.py downloaded.xlsx daily.json staged.xlsx
This script never accesses Drive, sends messages or marks an upload successful.
"""
import argparse,calendar,copy,json,posixpath,zipfile
from pathlib import Path
from datetime import date,datetime,timedelta
from decimal import Decimal
from xml.etree import ElementTree as ET
from openpyxl import load_workbook
from openpyxl.styles import Alignment,Font,PatternFill
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.workbook.properties import CalcProperties

MONTHS=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre']
D=lambda v:Decimal(str(v)).quantize(Decimal('.01'))
WHITE=PatternFill('solid',fgColor='FFFFFFFF',bgColor='FFFFFFFF')
RED_FONT='FFFF0000';GREEN_FONT='FF008000';BLACK_FONT='FF000000'

def row_date(value,year):
    if isinstance(value,(date,datetime)):return value.date() if isinstance(value,datetime) else value
    if not isinstance(value,str):return None
    parts=value.strip().lower().split()
    if len(parts)<2 or not parts[0].isdigit():return None
    month=parts[1]
    if month=='otubre':month='octubre'
    if month not in MONTHS:return None
    yy=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else year
    try:return date(yy,MONTHS.index(month)+1,int(parts[0]))
    except ValueError:return None

def restore_cache(path,caches):
    NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main';REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    ET.register_namespace('',NS)
    with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
    book=ET.fromstring(files['xl/workbook.xml']);rels=ET.fromstring(files['xl/_rels/workbook.xml.rels']);targets={r.attrib['Id']:r.attrib['Target'] for r in rels}
    for sh in book.find('{'+NS+'}sheets'):
        name=sh.attrib['name'];t=targets[sh.attrib['{'+REL+'}id']];file=t.lstrip('/') if t.startswith('/') else posixpath.normpath('xl/'+t)
        if not caches.get(name):continue
        tree=ET.fromstring(files[file])
        for c in tree.iter('{'+NS+'}c'):
            ref=c.attrib.get('r')
            if ref in caches[name] and c.find('{'+NS+'}f') is not None:
                v=c.find('{'+NS+'}v')
                if v is None:v=ET.SubElement(c,'{'+NS+'}v')
                v.text=str(caches[name][ref]);c.attrib.pop('t',None)
        files[file]=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)

def update(src,payload,out):
    target=date.fromisoformat(payload['business_date'])
    assert payload['gym']=='Anytime Fitness Sant Adria'
    assert payload['membr_available'] is True,'Membr unavailable: do not invent zeros or overwrite valid data'
    assert payload['mailbox_search_succeeded'] is True,'Failed mailbox search: leave original unchanged'
    total=D(payload['pos_total_net']);card=D(payload['pos_card']);other=D(payload['pos_noncard_net'])
    assert total==card+other,'POS method totals do not reconcile'
    reports_found=payload['payment_report_found'] is True
    bank=D(payload['payment_reports_total']) if reports_found else Decimal('0.00')
    difference=bank-card if reports_found else Decimal('0.00')
    values=load_workbook(src,data_only=True);wb=load_workbook(src,data_only=False)
    names=wb.sheetnames[:]
    caches={s.title:{c.coordinate:values[s.title][c.coordinate].value for row in s for c in row if c.data_type=='f' and values[s.title][c.coordinate].value is not None} for s in wb}
    year=str(target.year)
    if year not in wb.sheetnames:
        existing=[int(n) for n in wb.sheetnames if n.isdigit()]
        assert existing and target.year==max(existing)+1,'Only a new annual tab may be created'
        prior=wb[str(max(existing))];ws=wb.create_sheet(year,0);caches[year]={}
        for key,dim in prior.column_dimensions.items():ws.column_dimensions[key]=copy.copy(dim)
        for c in range(1,9):ws.cell(3,c,prior.cell(3,c).value)._style=copy.copy(prior.cell(3,c)._style)
        dt=date(target.year,1,1);r=4
        while dt.year==target.year:
            ws.cell(r,2,f'{dt.day} {MONTHS[dt.month-1].capitalize()} {target.year}')
            for c in range(3,8):ws.cell(r,c,0).fill=WHITE;ws.cell(r,c).number_format='#,##0.00'
            ws.row_dimensions[r].height=16;dt+=timedelta(days=1);r+=1
    ws=wb[year]
    matches=[r for r in range(1,ws.max_row+1) if row_date(ws.cell(r,2).value,target.year)==target]
    if not matches:
        # Existing 2026 template ends in October; append later dates in the same year.
        dated=[(row_date(ws.cell(r,2).value,target.year),r) for r in range(1,ws.max_row+1)]
        dated=[(d,r) for d,r in dated if d is not None]
        assert dated,'No unambiguous daily date rows'
        last,lastrow=max(dated,key=lambda x:x[0]);assert last<target and last.year==target.year
        dt=last+timedelta(days=1);r=lastrow+1
        while dt<=target:
            ws.cell(r,2,f'{dt.day} {MONTHS[dt.month-1].capitalize()}')
            for c in range(3,8):ws.cell(r,c,0).fill=WHITE;ws.cell(r,c).number_format='#,##0.00'
            ws.row_dimensions[r].height=16
            if dt==target:matches=[r]
            dt+=timedelta(days=1);r+=1
    assert len(matches)==1,'Ambiguous date: leave original unchanged'
    r=matches[0]
    before={(s.title,c.coordinate):c.value for s in wb for row in s for c in row if not (s.title==year and c.row==r and 3<=c.column<=7)}
    h_hidden=bool(ws.column_dimensions['H'].hidden)
    ws.cell(r,3,float(total));ws.cell(r,4,f'=C{r}-E{r}');ws.cell(r,5,float(other));ws.cell(r,6,float(bank))
    ws.cell(r,7,f'=F{r}-D{r}' if reports_found else 0)
    caches[year][f'D{r}']=float(card)
    caches[year][f'G{r}']=float(difference)
    if not reports_found:caches[year].pop(f'G{r}',None)
    for c in range(3,8):
        cell=ws.cell(r,c);cell.number_format='#,##0.00;[Red]-#,##0.00';cell.fill=WHITE;cell.comment=None;cell.alignment=Alignment(vertical='center',wrap_text=False)
    ws.row_dimensions[r].height=16
    # Latest approval: white cells; red/green numbers, black for missing data.
    font_colour=(GREEN_FONT if difference==0 else RED_FONT) if reports_found else BLACK_FONT
    difference_font=copy.copy(ws.cell(r,7).font);difference_font.color=font_colour;ws.cell(r,7).font=difference_font
    ws.cell(r,7).number_format='#,##0.00;-#,##0.00;0.00'
    # Column H (comments): keep whatever visibility the current original has (approved by Victor 2026-10-21).
    target_range=f'G{r}'
    for cf in list(ws.conditional_formatting._cf_rules):
        if str(cf.sqref)==target_range:del ws.conditional_formatting._cf_rules[cf]
    if reports_found:
        ws.cell(r,7).fill=WHITE
        # Verified single-date rules must outrank column-wide missing-data guards.
        for rules in ws.conditional_formatting._cf_rules.values():
            for rule in rules:rule.priority+=2
        red=FormulaRule(formula=[f'AND(ISNUMBER(G{r}),ROUND(G{r},2)<>0)'],fill=WHITE,font=Font(color=RED_FONT),stopIfTrue=True);red.priority=1
        green=FormulaRule(formula=[f'AND(ISNUMBER(G{r}),ROUND(G{r},2)=0)'],fill=WHITE,font=Font(color=GREEN_FONT),stopIfTrue=True);green.priority=2
        ws.conditional_formatting.add(target_range,red)
        ws.conditional_formatting.add(target_range,green)
    wb.calculation=CalcProperties(calcId=191029,fullCalcOnLoad=True)
    wb.save(out);restore_cache(out,caches)
    saved=load_workbook(out,data_only=False);cv=load_workbook(out,data_only=True)
    assert saved.sheetnames==names or (year not in names and saved.sheetnames==[year]+names)
    assert all(saved[s][cell].value==v for (s,cell),v in before.items()),'Unexpected change outside authorized date cells'
    assert [D(cv[year].cell(r,c).value) for c in range(3,8)]==[total,card,other,bank,difference]
    assert saved[year].row_dimensions[r].height==16
    assert bool(saved[year].column_dimensions['H'].hidden)==h_hidden,'Column H visibility changed'
    color=saved[year].cell(r,7).fill.fgColor.rgb[-6:]
    assert color=='FFFFFF' and saved[year].cell(r,7).fill.bgColor.rgb=='FFFFFFFF'
    assert saved[year].cell(r,7).font.color.rgb==font_colour
    result={'business_date':str(target),'year_tab':year,'row':r,'file':str(out),'pos_total_net':str(total),'pos_card':str(card),'pos_noncard_net':str(other),'payment_reports_total':str(bank),'difference':str(difference),'payment_report_found':reports_found,'missing_data_zero_is_white':not reports_found,'tabs':saved.sheetnames,'only_target_values_changed':True,'column_H_hidden':h_hidden}
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('payload');p.add_argument('output');a=p.parse_args()
    print(json.dumps(update(Path(a.source),json.loads(Path(a.payload).read_text()),Path(a.output)),ensure_ascii=False))
