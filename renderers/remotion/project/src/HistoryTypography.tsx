import React, {useEffect, useState} from 'react';
import {cancelRender, continueRender, delayRender, staticFile} from 'remotion';
import {captionLayout} from './directorData';
import type {Fonts} from './types';

export const historyFontStack = (english='Times New Roman',chinese='History Serif') => `"${english}", "${chinese}", serif`;

/** One licensed static Heavy face for all Chinese text; fail instead of silently substituting sans. */
export function HistoryTypography() {
  const [handle]=useState(()=>delayRender('Loading History Serif Heavy'));
  const url=staticFile('fonts/history-serif-heavy.otf');
  useEffect(()=>{
    document.fonts.load('900 30px "History Serif"','历史').then(async faces=>{
      if(!faces.length)throw new Error('History Serif Heavy did not load.');
      await document.fonts.ready;
      continueRender(handle);
    }).catch(cancelRender);
  },[handle,url]);
  return <style>{`@font-face {font-family:"History Serif";src:url("${url}") format("opentype");font-style:normal;font-weight:900;font-display:block;}`}</style>;
}

/** Exact SVG text lengths share the caption's audit geometry, including the compact backing. */
export function HistoryCaption({text,width,height,fonts}: {text:string;width:number;height:number;fonts?:Fonts}) {
  const caption=captionLayout(text,width,height);
  if(!caption.text)return null;
  const opacity=Math.max(0,Math.min(1,fonts?.background_opacity??.18));
  // Keep old explicit font families, but a legacy heavy outline must not obscure the new serif glyphs.
  const strokeWidth=Math.min(1.2,fonts?.outline_width??1)*width/1280;
  return <svg width={width} height={height} style={{position:'absolute',inset:0,pointerEvents:'none',fontFamily:historyFontStack(fonts?.english,fonts?.subtitle??fonts?.chinese),fontWeight:fonts?.subtitle_weight??900,fontSynthesis:'none'}} data-caption-lines={caption.lines.length}>
    <rect x={caption.box.x} y={caption.box.y} width={caption.box.width} height={caption.box.height} rx="3" fill="#1d2525" opacity={opacity}/>
    {caption.lines.map((line,i)=><text key={i} x={width/2} y={caption.box.y+caption.paddingY+caption.fontSize*.97+i*caption.lineHeight}
      textAnchor="middle" fontSize={caption.fontSize} textLength={caption.lineWidths[i]} lengthAdjust="spacingAndGlyphs"
      fill={fonts?.subtitle_color??'#fff'} stroke={fonts?.outline_width && fonts.outline_width<=1.2?fonts.outline_color??'#292824':'#292824'} strokeWidth={strokeWidth} strokeLinejoin="round" paintOrder="stroke">{line}</text>)}
  </svg>;
}
