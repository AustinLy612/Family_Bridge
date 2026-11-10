import { motion } from "framer-motion";

export type KeeperMood = "quiet" | "hopeful" | "hurt" | "bright";

export function LanternKeeper({ mood, glow, reducedMotion }: { mood: KeeperMood; glow: number; reducedMotion: boolean }) {
  const moodDescription = {
    quiet: "withdrawn, but listening",
    hopeful: "carefully hopeful",
    hurt: "discouraged and needing space",
    bright: "seen and encouraged",
  }[mood];
  return (
    <motion.div
      className={`lantern-keeper mood-${mood}`}
      animate={reducedMotion ? undefined : mood === "bright" ? { y: [0, -8, 0] } : { y: [0, -2, 0] }}
      transition={{ duration: mood === "bright" ? 1.2 : 4, repeat: Infinity, ease: "easeInOut" }}
      role="img"
      aria-label={`Moss, the little lantern keeper, looks ${moodDescription}`}
    >
      <svg viewBox="0 0 270 260" role="img" aria-hidden="true">
        <defs>
          <radialGradient id="keeperLantern" cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#fff8c6" />
            <stop offset=".45" stopColor="#ffd568" stopOpacity=".92" />
            <stop offset="1" stopColor="#f7a93c" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="fur" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#d8b98a" /><stop offset="1" stopColor="#9c765a" />
          </linearGradient>
        </defs>
        <ellipse cx="135" cy="236" rx="84" ry="13" fill="#041c20" opacity=".35" />
        <circle className="keeper-lantern-glow" cx="190" cy="173" r={36 + glow * 0.18} fill="url(#keeperLantern)" opacity={0.42 + glow / 180} />
        <g className="keeper-ears">
          <path d="M70 76 53 25q48 20 66 53M174 77l35-46q-48 10-67 48" fill="url(#fur)" stroke="#6f5948" strokeWidth="6" strokeLinejoin="round" />
          <path d="M71 70 60 39q27 14 40 35M169 71l25-27q-27 8-39 31" fill="#e9ceb0" opacity=".72" />
        </g>
        <path d="M64 139q0-75 71-75t72 75v42q-3 55-72 55t-71-55Z" fill="url(#fur)" stroke="#6f5948" strokeWidth="6" />
        <path d="M92 207q-15 15-14 37M175 207q18 16 17 37" stroke="#6f5948" strokeWidth="20" strokeLinecap="round" />
        <path d="M69 156q-35 20-35 50 33 12 55-10" fill="#a57c5f" stroke="#6f5948" strokeWidth="6" strokeLinecap="round" />
        <ellipse cx="135" cy="154" rx="47" ry="54" fill="#e6cfac" opacity=".9" />
        <g className="keeper-face">
          <path className="keeper-brows" d={mood === "hurt" ? "M99 98q10-7 21 2M150 100q11-9 21-2" : mood === "bright" ? "M99 98q10-5 21 0M150 98q10-5 21 0" : "M100 100q10-2 20 1M150 101q10-3 20-1"} fill="none" stroke="#765d4d" strokeWidth="3.5" strokeLinecap="round" />
          {mood === "bright" ? (
            <>
              <ellipse cx="111" cy="112" rx="6" ry="8" fill="#343637" /><ellipse cx="159" cy="112" rx="6" ry="8" fill="#343637" />
              <circle cx="109" cy="109" r="1.8" fill="#fff9dd" /><circle cx="157" cy="109" r="1.8" fill="#fff9dd" />
            </>
          ) : (
            <path d={`M101 ${mood === "hurt" ? 113 : 111}q10 ${mood === "hurt" ? 7 : -2} 20 0M149 ${mood === "hurt" ? 113 : 111}q10 ${mood === "hurt" ? 7 : -2} 20 0`} fill="none" stroke="#3d3a38" strokeWidth="6" strokeLinecap="round" />
          )}
          <circle className="keeper-blush" cx="96" cy="134" r="7" fill="#c47f72" opacity={mood === "bright" ? .28 : .08} />
          <circle className="keeper-blush" cx="174" cy="134" r="7" fill="#c47f72" opacity={mood === "bright" ? .28 : .08} />
        </g>
        <path d={mood === "bright" ? "M122 143q13 14 27 0" : mood === "hurt" ? "M122 151q13-11 27 0" : "M124 148q11 4 22 0"} fill="none" stroke="#4b3c37" strokeWidth="5" strokeLinecap="round" />
        <circle cx="135" cy="130" r="5" fill="#765c4d" />
        <path d="M85 169q48 28 101 0" fill="none" stroke="#4a7070" strokeWidth="14" strokeLinecap="round" />
        <path d="M189 147v61M166 162h47M171 162l6-26h25l7 26" stroke="#5b493b" strokeWidth="6" fill="none" strokeLinecap="round" />
        <rect x="171" y="161" width="38" height="48" rx="7" fill="#d69f3b" stroke="#5b493b" strokeWidth="5" />
        <rect x="179" y="169" width="22" height="31" rx="4" fill="#ffdb6a" opacity={0.25 + glow / 130} />
        <motion.ellipse
          cx="190" cy="185" rx="5" ry={8 + glow / 35} fill="#fff4a3"
          animate={reducedMotion ? undefined : { opacity: [.55, 1, .7], scaleY: [.86, 1.08, .9] }}
          transition={{ duration: 1.7, repeat: Infinity, ease: "easeInOut" }}
          style={{ transformOrigin: "190px 193px" }}
        />
        {(mood === "bright" || mood === "hopeful") && (
          <g className="keeper-sparkles" fill="#ffe895">
            <path d="m222 115 4 9 9 4-9 4-4 9-4-9-9-4 9-4Z" />
            {mood === "bright" && <path d="m69 104 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z" />}
          </g>
        )}
      </svg>
      <span className="keeper-reaction" aria-hidden="true">
        {mood === "hurt" ? "needs a pause" : mood === "bright" ? "feels understood" : mood === "hopeful" ? "notices you" : "listening quietly"}
      </span>
      <span className="keeper-name">Moss · lantern keeper</span>
    </motion.div>
  );
}
