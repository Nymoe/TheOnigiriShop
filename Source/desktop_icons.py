"""Small antialiased desktop icons rendered with the standard library."""
import base64
import struct
import tkinter as tk
import zlib


def checkbox_icon(master,fill,border,ink,checked,size=22):
    """Rounded checkbox with a supersampled outline and tick; includes label gap."""
    rgb=lambda c:tuple(v//257 for v in master.winfo_rgb(c))
    colours=[rgb(fill),rgb(border),rgb(ink)];pixels=[]
    def distance(x,y,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1]
        t=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        return ((x-a[0]-t*dx)**2+(y-a[1]-t*dy)**2)**.5
    for y in range(size):
        for x in range(size+8):
            sums=[0,0,0];covered=0
            for sy in range(4):
                for sx in range(4):
                    px=(x+(sx+.5)/4)/size;py=(y+(sy+.5)/4)/size
                    dx=max(.21-px,0,px-.79);dy=max(.21-py,0,py-.79)
                    outer=(dx*dx+dy*dy)**.5<=.18
                    if not outer:continue
                    inner=(max(.21-px,0,px-.79)**2+max(.21-py,0,py-.79)**2)**.5<=.12
                    tick=checked and min(distance(px,py,(.26,.51),(.43,.68)),distance(px,py,(.43,.68),(.76,.32)))<.047
                    colour=colours[2 if tick else 0 if inner or checked else 1]
                    for i in range(3):sums[i]+=colour[i]
                    covered+=1
            pixels.extend((*[round(v/covered) if covered else 0 for v in sums],round(covered/16*255)))
    return rgba_photo(master,size+8,size,pixels)


def notebook_tab_icon(master,fill,border):
    colours=[tuple(v//257 for v in master.winfo_rgb(c)) for c in (fill,border)]
    width,height,radius=28,24,6;pixels=[]
    for y in range(height):
        for x in range(width):
            sums=[0,0,0];covered=0
            for sy in range(4):
                for sx in range(4):
                    px=x+(sx+.5)/4;py=y+(sy+.5)/4
                    distance=(max(radius-px,0,px-(width-radius))**2+max(radius-py,0)**2)**.5
                    if distance>radius:continue
                    inside=distance<=radius-1 and px>=1 and px<=width-1 and py>=1
                    for i,value in enumerate(colours[0 if inside else 1]):sums[i]+=value
                    covered+=1
            pixels.extend((*[round(v/covered) if covered else 0 for v in sums],round(255*covered/16)))
    return rgba_photo(master,width,height,pixels)


def rgba_photo(master,width,height,pixels):
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+bytes(pixels[y*width*4:(y+1)*width*4]) for y in range(height))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
    return tk.PhotoImage(master=master,data=base64.b64encode(png))


def eye_icon(master,color,visible=False,size=22):
    rgb=tuple(channel//257 for channel in master.winfo_rgb(color))
    pixels=[];samples=4
    for py in range(size):
        for px in range(size):
            covered=0
            for sy in range(samples):
                for sx in range(samples):
                    x=(px+(sx+.5)/samples)/size-.5
                    y=(py+(sy+.5)/samples)/size-.5
                    outer=abs(x)<=.44 and abs(y)<=.25*(1-(x/.44)**2)
                    inner=abs(x)<.37 and abs(y)<.19*(1-(x/.37)**2)
                    pupil=x*x+y*y<=.085**2
                    slash=visible and abs(y-x)<.038 and abs(x)<.39
                    covered+=bool((outer and not inner) or pupil or slash)
            pixels.extend((*rgb,round(255*covered/(samples*samples))))
    return rgba_photo(master,size,size,pixels)
