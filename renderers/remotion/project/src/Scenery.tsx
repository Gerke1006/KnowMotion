import React from 'react';
import type {Camera, DirectorSceneData} from './directorTypes';

type Environment=DirectorSceneData['environment'];
export const sceneryTransform=(camera:Camera,depth:number)=>`translate(${(.5-camera.x)*1280*depth} ${(.5-camera.y)*720*depth}) translate(640 360) scale(${1+(camera.zoom-1)*depth}) translate(-640 -360)`;

/** Neutral environmental space only: people, gates, documents and routes must be explicit objects. */
export function Scenery({environment,camera}: {environment:Environment;camera:Camera}) {
  const layer=(depth:number)=>sceneryTransform(camera,depth);
  const palette:Record<Environment,[string,string]>={
    mountains:['#e5ece6','#dce6db'],road:['#f0ecda','#e7e3ce'],desert:['#f3dfbe','#e7c591'],
    city_gate:['#e5e6df','#d4d1be'],interior:['#d6c6a8','#b9a486'],map:['#f2ebd9','#e6dbc0'],
  };
  const [sky,ground]=palette[environment];
  return <g data-environment={environment}>
    <defs>
      <linearGradient id="director-sky" x1="0" y1="0" x2="0" y2="1"><stop stopColor={sky}/><stop offset="1" stopColor={ground}/></linearGradient>
      <linearGradient id="director-mist" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#edf0e5" stopOpacity="0"/><stop offset=".55" stopColor="#edf0e5" stopOpacity=".64"/><stop offset="1" stopColor="#edf0e5" stopOpacity="0"/></linearGradient>
      <pattern id="director-grain" width="63" height="71" patternUnits="userSpaceOnUse"><path d="M6 4h1M37 51h1M54 19h2M12 61h1" stroke="#6e6c59" strokeWidth="1" opacity=".10"/></pattern>
      <pattern id="director-lattice" width="64" height="64" patternUnits="userSpaceOnUse"><path d="M0 0H64V64H0ZM32 0V64M0 32H64" fill="none" stroke="#8b806b" strokeWidth="2" opacity=".42"/></pattern>
    </defs>
    <rect x="-640" y="-360" width="2560" height="1440" fill="url(#director-sky)"/>
    {environment==='mountains' && <>
      <g data-depth="far" transform={layer(.16)} data-scenery-feature="mist-ridges">
        <path d="M-300 470L-100 185L13 285L113 154L249 350L370 217L470 392L577 262L686 365L839 162L910 232L1034 95L1163 278L1265 191L1530 439V820H-300Z" fill="#809c91" opacity=".36"/>
        <path d="M13 285L113 154L88 306L137 262L180 339M910 232L1034 95L1000 289L1052 246L1108 339" fill="none" stroke="#dce6dc" strokeWidth="3" opacity=".6"/>
      </g>
      <g data-depth="middle" transform={layer(.42)} data-scenery-feature="valley-shelves">
        <path d="M-250 419L-32 263L70 363L145 319L292 474L415 503L557 532L766 515L927 424L1070 330L1171 374L1310 268L1530 437V850H-250Z" fill="#91a99a" opacity=".54"/>
        <path d="M-180 521Q156 432 445 520Q626 573 835 524Q1119 410 1490 502V840H-180Z" fill="#c5d1ba"/>
        <rect x="-240" y="380" width="1760" height="210" fill="url(#director-mist)"/>
      </g>
      <g data-depth="near" transform={layer(.78)} data-scenery-feature="rock-edges">
        <path d="M-280 810L-280 550L-108 501L-10 531L46 606L139 639L190 810M1118 810L1159 660L1234 625L1293 541L1416 513L1540 581V810" fill="#687f70" opacity=".48"/>
        <path d="M-52 563L5 585L35 631M1247 660L1308 594L1390 578" fill="none" stroke="#455f54" strokeWidth="3" opacity=".32"/>
      </g>
    </>}
    {environment==='road' && <>
      <g data-depth="far" transform={layer(.16)} data-scenery-feature="open-plain">
        <path d="M-300 421Q5 367 289 420Q535 380 811 412Q1130 365 1540 419V850H-300Z" fill="#aab6a0" opacity=".43"/>
        <path d="M-240 447Q171 411 533 447Q962 396 1510 455V850H-240Z" fill="#bdc3a8"/>
      </g>
      <g data-depth="middle" transform={layer(.45)} data-scenery-feature="diagonal-road">
        <path d="M183 421Q403 466 730 522Q1001 568 1570 690V880H980Q803 681 554 576Q328 487 183 421Z" fill="#dfcfa9"/>
        <path d="M193 431Q465 500 693 554Q1014 643 1198 801M233 435Q543 493 796 544Q1098 609 1460 704" fill="none" stroke="#b9a989" strokeWidth="2" opacity=".34"/>
        <path d="M-200 555Q171 492 370 525Q576 560 745 681L1014 841H-200Z" fill="#bbc0a3" opacity=".68"/>
      </g>
      <g data-depth="near" transform={layer(.80)} data-scenery-feature="verge-grasses">
        <path d="M-140 742Q48 608 234 662L350 810H-140M1110 810L1221 681Q1336 645 1490 697V810" fill="#8f9f80" opacity=".6"/>
        <path d="M66 700L54 647M66 700L88 657M94 715L108 674M1260 736L1250 686M1260 736L1281 695M1328 743L1312 702" stroke="#71866d" strokeWidth="3" fill="none" opacity=".55"/>
      </g>
    </>}
    {environment==='desert' && <>
      <g data-depth="far" transform={layer(.13)} data-scenery-feature="distant-dunes">
        <circle cx="1010" cy="171" r="62" fill="#fff1cb" opacity=".58"/>
        <path d="M-300 455Q-30 291 307 409Q670 492 919 371Q1219 258 1540 419V850H-300Z" fill="#d0aa75" opacity=".48"/>
      </g>
      <g data-depth="middle" transform={layer(.40)} data-scenery-feature="sweeping-dune">
        <path d="M-300 571Q126 323 501 444Q927 574 1540 428V850H-300Z" fill="#dcc092"/>
        <path d="M-300 571Q126 323 501 444Q333 453 217 516Q-17 621-300 660Z" fill="#eed4a5"/>
        <path d="M-180 583Q182 437 466 467Q954 618 1470 493" stroke="#b89464" strokeWidth="2" fill="none" opacity=".22"/>
      </g>
      <g data-depth="near" transform={layer(.74)} data-scenery-feature="wind-ripples">
        <path d="M-250 735Q171 590 532 690Q1042 808 1540 605V850H-250Z" fill="#cfa66f" opacity=".46"/>
        {[0,1,2,3].map(i=><path key={i} d={`M${-150+i*25} ${678+i*19}Q110 ${613+i*21} 333 ${662+i*20}M${1002+i*24} ${706+i*16}Q1280 ${638+i*20} 1490 ${654+i*18}`} fill="none" stroke="#b68c5b" strokeWidth="1.5" opacity=".25"/>)}
      </g>
    </>}
    {environment==='city_gate' && <>
      <g data-depth="far" transform={layer(.14)} data-scenery-feature="city-wall-wings">
        <path d="M-360 454V246H-60V225H-10V246H72V225H121V246H204V225H253V246H337V225H386V246H447V454M939 454V257H993V235H1042V257H1125V235H1174V257H1257V235H1306V257H1570V454" fill="#b1b2a0"/>
        <path d="M-300 306H447M-300 374H447M939 317H1540M939 385H1540M36 246V454M184 246V454M332 246V454M1075 257V454M1223 257V454" stroke="#8f9485" strokeWidth="2" opacity=".38"/>
      </g>
      <g data-depth="middle" transform={layer(.43)} data-scenery-feature="stone-plaza">
        <path d="M-350 454H1630V900H-350Z" fill="#d1cbb6"/>
        <path d="M-340 497H1620M-340 565H1620M-340 671H1620M-220 850L283 454M287 850L487 454M789 850L691 454M1292 850L895 454M1790 850L1100 454" stroke="#a9a792" strokeWidth="2" opacity=".44"/>
        <path d="M-300 451H449M939 453H1540" stroke="#878c7d" strokeWidth="9" opacity=".5"/>
      </g>
      <g data-depth="near" transform={layer(.76)} data-scenery-feature="courtyard-corners">
        <path d="M-180 790V570L-50 537L30 561V790M1264 790V576L1338 546L1480 575V790" fill="#8d9382" opacity=".55"/>
        <path d="M-180 574L-50 544L30 568M1264 584L1338 553L1480 584" fill="none" stroke="#697565" strokeWidth="5" opacity=".5"/>
      </g>
    </>}
    {environment==='interior' && <>
      <g data-depth="far" transform={layer(.12)} data-scenery-feature="lattice-light">
        <rect x="-300" y="-180" width="1880" height="650" fill="#d2c5a9"/>
        <rect x="181" y="111" width="296" height="302" fill="#eee7d3"/><rect x="181" y="111" width="296" height="302" fill="url(#director-lattice)"/>
        <path d="M181 111H477V413H181Z" stroke="#807461" strokeWidth="10" fill="none"/>
        <path d="M591 132H1078V406H591Z" fill="#c4b69a" stroke="#a49478" strokeWidth="3"/>
        <path d="M607 147H1062V391H607Z" stroke="#dacfba" fill="none" strokeWidth="2"/>
      </g>
      <g data-depth="middle" transform={layer(.44)} data-scenery-feature="timber-floor">
        <path d="M-320 458H1600V880H-320Z" fill="#b9a98c"/>
        <path d="M-320 459H1600" stroke="#77614c" strokeWidth="13"/>
        <path d="M-110 840L325 458M293 840L482 458M697 840L640 458M1101 840L797 458M1504 840L955 458M-320 544H1600M-320 673H1600" stroke="#8f7d61" strokeWidth="2" opacity=".38"/>
        <path d="M181 413L477 413L846 719L185 719Z" fill="#f7eccd" opacity=".18"/>
      </g>
      <g data-depth="near" transform={layer(.81)} data-scenery-feature="timber-frame">
        <path d="M-190-190H65V840H-190M1218-190H1470V840H1218" fill="#6b5544"/>
        <path d="M24-35H1255V59H24Z" fill="#775941"/><path d="M65 61Q142 106 221 64M1063 64Q1145 106 1218 61" fill="none" stroke="#927150" strokeWidth="28"/>
        <path d="M57 66V795M1227 66V795" stroke="#a58b66" strokeWidth="4" opacity=".55"/>
      </g>
    </>}
    {environment==='map' && <>
      <g data-depth="far" transform={layer(.10)} data-scenery-feature="cartographic-grid">
        <rect x="-300" y="-180" width="1880" height="1080" fill="#eee5ce"/>
        {[-200,0,200,400,600,800,1000,1200,1400].map(x=><path key={x} d={`M${x} -160V880`} stroke="#b6b49a" strokeWidth="1" opacity=".28"/>)}
        {[-100,50,200,350,500,650,800].map(y=><path key={y} d={`M-300 ${y}H1580`} stroke="#b6b49a" strokeWidth="1" opacity=".28"/>)}
      </g>
      <g data-depth="middle" transform={layer(.32)} data-scenery-feature="survey-margins">
        <path d="M45 176V615H1235M45 207H56M45 244H56M45 281H56M45 318H56M45 355H56M45 392H56M45 429H56M45 466H56M45 503H56M45 540H56M45 577H56M121 615V604M235 615V604M349 615V604M463 615V604M577 615V604M691 615V604M805 615V604M919 615V604M1033 615V604M1147 615V604" fill="none" stroke="#a29f83" strokeWidth="1.3" opacity=".55"/>
        <path d="M126 180V274M79 227H173M126 189L115 231L126 218L137 231Z" fill="#919b84" stroke="#919b84" strokeWidth="1" opacity=".38"/>
        <circle cx="126" cy="227" r="37" fill="none" stroke="#a29f83" strokeWidth="1.2" opacity=".5"/>
      </g>
      <g data-depth="near" transform={layer(.60)} data-scenery-feature="paper-folds">
        <path d="M-210 687L1268 664L1480 810H-210Z" fill="#cbbd98" opacity=".16"/>
        <path d="M-140 691L1280 667" fill="none" stroke="#faf3df" strokeWidth="4" opacity=".6"/>
        <path d="M1088-130L1126 850" fill="none" stroke="#c1b38f" strokeWidth="2" opacity=".16"/>
      </g>
    </>}
    <rect x="-350" y="-200" width="1980" height="1120" fill="url(#director-grain)" pointerEvents="none"/>
  </g>;
}
