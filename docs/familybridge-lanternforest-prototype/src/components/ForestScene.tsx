import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { LanternKeeper, type KeeperMood } from "./LanternKeeper";

type ForestSceneProps = {
  lanternPower?: number;
  keeperMood?: KeeperMood;
  reducedMotion?: boolean;
  completed?: boolean;
  compact?: boolean;
  children?: ReactNode;
};

const fireflies = [
  [9, 34, 0.2], [15, 69, 1.3], [21, 46, 2.4], [29, 28, 0.8], [34, 73, 3.1],
  [42, 38, 1.9], [49, 62, 0.4], [57, 30, 2.8], [63, 68, 1.1], [70, 44, 3.6],
  [77, 24, 0.9], [83, 57, 2.1], [91, 36, 3.3], [95, 71, 1.6],
];

const driftingLeaves = [
  [13, 18, 0.4, "left"], [39, 12, 2.1, "right"], [73, 16, 1.2, "left"], [89, 27, 3.4, "right"],
] as const;

export function ForestScene({
  lanternPower = 38,
  keeperMood = "quiet",
  reducedMotion = false,
  completed = false,
  compact = false,
  children,
}: ForestSceneProps) {
  const x = useSpring(useMotionValue(0), { stiffness: 45, damping: 20 });
  const y = useSpring(useMotionValue(0), { stiffness: 45, damping: 20 });
  const farX = useTransform(x, (value) => value * 0.28);
  const farY = useTransform(y, (value) => value * 0.2);
  const nearX = useTransform(x, (value) => value * 1.55);
  const nearY = useTransform(y, (value) => value * 1.25);

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (reducedMotion) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    x.set(((event.clientX - bounds.left) / bounds.width - 0.5) * -12);
    y.set(((event.clientY - bounds.top) / bounds.height - 0.5) * -7);
  };

  const style = { "--lantern-power": `${lanternPower}%` } as CSSProperties;
  return (
    <div
      className={`forest-scene ${compact ? "forest-scene--compact" : ""} ${completed ? "is-complete" : ""}`}
      style={style}
      onPointerMove={handlePointerMove}
      onPointerLeave={() => { x.set(0); y.set(0); }}
    >
      <svg className="forest-sky" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="sky" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={completed ? "#315b63" : "#102f3b"} />
            <stop offset="0.55" stopColor={completed ? "#46756d" : "#17484d"} />
            <stop offset="1" stopColor="#09292d" />
          </linearGradient>
          <radialGradient id="moonGlow">
            <stop offset="0" stopColor="#eefccf" stopOpacity=".8" />
            <stop offset="1" stopColor="#d8f0c9" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="path" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#65867b" />
            <stop offset="1" stopColor="#c4aa78" />
          </linearGradient>
          <filter id="blur20"><feGaussianBlur stdDeviation="20" /></filter>
          <filter id="lanternGlow" x="-200%" y="-200%" width="500%" height="500%">
            <feGaussianBlur stdDeviation="18" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <rect width="1600" height="900" fill="url(#sky)" />
        <circle cx="1260" cy="160" r="170" fill="url(#moonGlow)" />
        <circle cx="1260" cy="160" r="56" fill="#e8f2cc" opacity=".36" />
        <g opacity=".25" fill="#82a58f">
          <path d="M0 420 Q180 250 360 420 T760 420 T1180 390 T1600 420 V900 H0Z" />
          <path d="M0 510 Q220 335 410 500 T820 490 T1240 500 T1600 470 V900 H0Z" fill="#436e68" />
        </g>
        <g className="mist" opacity=".18" fill="#e5f2dc" filter="url(#blur20)">
          <ellipse cx="400" cy="620" rx="420" ry="55" />
          <ellipse cx="1180" cy="550" rx="460" ry="48" />
        </g>
      </svg>

      <motion.svg className="forest-far" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" style={{ x: farX, y: farY }} aria-hidden="true">
        <defs>
          <linearGradient id="farTrees" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#2d6866" stopOpacity=".36" />
            <stop offset="1" stopColor="#123e40" stopOpacity=".82" />
          </linearGradient>
          <filter id="softFar"><feGaussianBlur stdDeviation="1.8" /></filter>
        </defs>
        <g fill="url(#farTrees)" filter="url(#softFar)">
          <path d="M40 680V280q55-55 110 0v400h-45V334q-10-22-21 0v346Zm240 0V355q45-45 90 0v325h-38V402q-8-18-17 0v278Zm990 0V310q52-51 103 0v370h-42V362q-10-20-20 0v318Zm190 0V365q43-42 85 0v315h-36V410q-8-17-16 0v270Z" />
          <path d="M0 463q168-132 333-26 168-160 360-34 181-124 344-9 167-157 363-31 98-51 200-14v332H0Z" opacity=".44" />
        </g>
        <g className="forest-star-field" fill="#f9e8a0">
          <circle cx="415" cy="236" r="2.2" /><circle cx="916" cy="182" r="1.7" /><circle cx="1110" cy="281" r="2" />
          <circle cx="675" cy="312" r="1.4" /><circle cx="1432" cy="235" r="1.8" />
        </g>
      </motion.svg>

      <div className="moonbeams" aria-hidden="true"><span /><span /><span /></div>

      <motion.svg className="forest-mid" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" style={{ x, y }} aria-hidden="true">
        <g fill="#0d3435">
          <path d="M0 0h245c-8 124-41 218-102 304-41 58-57 167-31 305L0 676Z" />
          <path d="M1600 0h-248c20 124 54 205 106 291 47 76 62 173 31 321l111 65Z" />
          <path d="M145 0c72 60 144 89 270 88-102 22-179 14-245-8 95 64 175 83 293 65-111 44-213 47-318 1Z" />
          <path d="M1455 0c-72 60-144 89-270 88 102 22 179 14 245-8-95 64-175 83-293 65 111 44 213 47 318 1Z" />
        </g>
        <g fill="#164645" opacity=".94">
          <path d="M160 900c-5-176 55-295 132-405 37-52 54-122 42-211 43 112 38 198-6 274-46 80-65 190-45 342Z" />
          <path d="M1395 900c2-165-45-289-112-391-38-58-53-128-37-209-48 107-48 194-8 270 47 89 64 196 46 330Z" />
          <path d="M487 900c-8-179 40-278 99-367 25-39 35-89 28-152 32 78 31 144 5 199-38 80-42 185-22 320Z" />
          <path d="M1115 900c8-179-40-278-99-367-25-39-35-89-28-152-32 78-31 144-5 199 38 80 42 185 22 320Z" />
        </g>
        <path d="M832 900c-68-165-42-271 80-380 62-55 90-109 81-161 40 111-10 192-71 260-68 76-62 170 35 281Z" fill="url(#path)" opacity=".54" />
        <g fill="#224f49">
          <path d="M0 700c104-57 166-41 241 23-66-17-102-7-142 28 82-10 144 13 202 82H0Z" />
          <path d="M1600 692c-112-41-184-17-254 55 72-27 132-14 176 22-89-8-154 20-205 90h283Z" />
        </g>
        <g className="hanging-vines" stroke="#193f3d" strokeWidth="7" fill="none">
          <path d="M260 0q-8 112 42 194" /><path d="M520 0q12 92-8 182" />
          <path d="M1085 0q-18 103 4 209" /><path d="M1370 0q4 98-43 191" />
        </g>
      </motion.svg>

      <Lantern x="19%" y="18%" scale={1.15} delay={0} />
      <Lantern x="32%" y="25%" scale={0.82} delay={0.7} />
      <Lantern x="68%" y="21%" scale={0.72} delay={1.1} />
      <Lantern x="84%" y="17%" scale={0.96} delay={0.4} />
      <Lantern x="58%" y="32%" scale={0.56} delay={1.6} />
      <Lantern x="45%" y="16%" scale={0.48} delay={2.2} />

      <div className="path-lights" aria-hidden="true">
        <i style={{ left: "54%", top: "63%" }} /><i style={{ left: "59%", top: "69%" }} /><i style={{ left: "65%", top: "76%" }} />
      </div>

      {!reducedMotion && fireflies.map(([left, top, delay], index) => (
        <span
          className="firefly"
          key={index}
          style={{ left: `${left}%`, top: `${top}%`, animationDelay: `${delay}s` }}
        />
      ))}

      {!reducedMotion && driftingLeaves.map(([left, top, delay, direction], index) => (
        <span key={`leaf-${index}`} className={`drifting-leaf drifting-leaf--${direction}`} style={{ left: `${left}%`, top: `${top}%`, animationDelay: `${delay}s` }} aria-hidden="true">❧</span>
      ))}

      <motion.svg className="forest-foreground" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" style={{ x: nearX, y: nearY }} aria-hidden="true">
        <g fill="#072829">
          <path d="M0 0h112q37 130-10 260-34 94 8 223L0 560Z" />
          <path d="M1600 0h-98q-43 119 2 248 35 99-9 235l105 76Z" />
          <path d="M0 0h462q-145 35-235 121 104-44 240-24-163 37-287 141Q98 182 0 215Z" />
          <path d="M1600 0h-450q137 32 229 119-112-39-239-17 152 35 276 135 83-50 184-24Z" />
        </g>
        <g className="foreground-ferns" fill="#0a3633">
          <path d="M0 900V727q74-86 184-65-76 20-119 74 79-46 177-14-88 17-150 76 118-50 210 13v89Z" />
          <path d="M1600 900V714q-81-71-183-46 72 16 118 72-86-43-177-4 90 12 153 72-117-43-209 18v74Z" />
        </g>
      </motion.svg>

      <div className={`keeper-stage keeper-stage--${keeperMood}`} aria-live="polite">
        <LanternKeeper mood={keeperMood} glow={lanternPower} reducedMotion={reducedMotion} />
      </div>
      <div className="forest-vignette" />
      {children && <div className="scene-content">{children}</div>}
    </div>
  );
}

function Lantern({ x, y, scale, delay }: { x: string; y: string; scale: number; delay: number }) {
  return (
    <div className="hanging-lantern" style={{ left: x, top: y, transform: `scale(${scale})`, animationDelay: `${delay}s` }}>
      <span className="lantern-aura" />
      <span className="lantern-cap" />
      <span className="lantern-body"><i /></span>
      <span className="lantern-tassel" />
    </div>
  );
}
