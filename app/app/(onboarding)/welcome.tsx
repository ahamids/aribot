// Onboarding carousel — three swipeable cards from the design. After the last
// card, the user lands on the bot connection setup screen.

import React, { useRef, useState } from 'react';
import {
  Dimensions,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  ScrollView,
  Text,
  View,
} from 'react-native';
import Svg, { Path, Polygon, Rect, Text as SvgText, Circle } from 'react-native-svg';
import { useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { MascotSlot } from '@/mascot/MascotSlot';
import { AT, stickerShadow } from '@/theme/tokens';

const { width: SCREEN_W } = Dimensions.get('window');

type CardSpec = {
  pose: 'thumbsup' | 'serious';
  tone: 'mint' | 'yellow' | 'coral';
  title: string;
  body: string;
  art: React.ReactNode;
};

function CardA() {
  return (
    <Svg width={280} height={120} viewBox="0 0 280 120">
      <Rect x={10} y={30} width={80} height={60} rx={14} fill={AT.peri} stroke={AT.plum} strokeWidth={3} />
      <SvgText x={50} y={64} textAnchor="middle" fontSize={11} fontWeight="800" fill="#fff">YOUR SERVER</SvgText>
      <SvgText x={50} y={78} textAnchor="middle" fontSize={9} fill="#fff">aribot.py</SvgText>
      <Path d="M95 60 Q140 30 185 60" fill="none" stroke={AT.plum} strokeWidth={3} strokeDasharray="6 4" />
      <Polygon points="178,55 192,60 178,65" fill={AT.plum} />
      <Rect x={190} y={30} width={80} height={60} rx={14} fill={AT.coral} stroke={AT.plum} strokeWidth={3} />
      <SvgText x={230} y={64} textAnchor="middle" fontSize={11} fontWeight="800" fill="#fff">ARIBOT iOS</SvgText>
      <SvgText x={230} y={78} textAnchor="middle" fontSize={9} fill="#fff">this app</SvgText>
    </Svg>
  );
}

function CardB() {
  return (
    <Svg width={200} height={120} viewBox="0 0 200 120">
      <Rect x={40} y={40} width={120} height={70} rx={14} fill={AT.yellow} stroke={AT.plum} strokeWidth={3.5} />
      <Path d="M70 40 V28 a30 30 0 0 1 60 0 V40" fill="none" stroke={AT.plum} strokeWidth={3.5} strokeLinecap="round" />
      <Circle cx={100} cy={72} r={10} fill={AT.plum} />
      <Rect x={96} y={78} width={8} height={16} rx={2} fill={AT.plum} />
      <SvgText x={100} y={106} textAnchor="middle" fontSize={9} fontWeight="800" fill={AT.plum}>SEALED-BOX</SvgText>
    </Svg>
  );
}

function CardC() {
  const items = [
    { m: 'PAPER',  bg: '#fff',          sub: 'Sim only.' },
    { m: 'SHADOW', bg: AT.yellow,       sub: 'Dry-run real auth.' },
    { m: 'LIVE',   bg: AT.pnlRedSoft,   sub: 'Real money.' },
  ];
  return (
    <View style={{ flexDirection: 'row', gap: 8, marginTop: 20 }}>
      {items.map(it => (
        <View
          key={it.m}
          style={[
            {
              flex: 1,
              paddingHorizontal: 10,
              paddingVertical: 14,
              borderRadius: 16,
              borderWidth: AT.ol2,
              borderColor: AT.plum,
              backgroundColor: it.bg,
              alignItems: 'center',
            },
            stickerShadow(AT.plum),
          ]}
        >
          <Text style={{ fontSize: 14, fontWeight: '900', letterSpacing: 0.5, color: AT.plum }}>{it.m}</Text>
          <Text style={{ fontSize: 10, color: AT.plumMid, marginTop: 4, textAlign: 'center', lineHeight: 13 }}>
            {it.sub}
          </Text>
        </View>
      ))}
    </View>
  );
}

const CARDS: CardSpec[] = [
  {
    pose: 'thumbsup',
    tone: 'mint',
    title: 'Connect your bot',
    body: 'Aribot runs on your own VPS. Paste its URL + a bearer token and we’ll do a handshake.',
    art: <CardA />,
  },
  {
    pose: 'serious',
    tone: 'yellow',
    title: 'Add your Bybit keys',
    body: 'Keys are encrypted on this device before they go anywhere. Even we can’t read them.',
    art: <CardB />,
  },
  {
    pose: 'serious',
    tone: 'coral',
    title: 'Pick a mode',
    body: 'Start safe. Move to live only when you’re comfy.',
    art: <CardC />,
  },
];

export default function OnboardingCarousel() {
  const router = useRouter();
  const [idx, setIdx] = useState(0);
  const scrollRef = useRef<ScrollView>(null);

  function onScroll(e: NativeSyntheticEvent<NativeScrollEvent>) {
    const i = Math.round(e.nativeEvent.contentOffset.x / SCREEN_W);
    if (i !== idx) setIdx(i);
  }

  function next() {
    if (idx < CARDS.length - 1) {
      scrollRef.current?.scrollTo({ x: (idx + 1) * SCREEN_W, animated: true });
    } else {
      router.push('/(onboarding)/bot-setup');
    }
  }

  return (
    <Screen scroll={false}>
      <View style={{ flexDirection: 'row', justifyContent: 'flex-end', paddingHorizontal: 6, paddingVertical: 4 }}>
        <Pressable onPress={() => router.push('/(onboarding)/bot-setup')} hitSlop={12}>
          <Text style={{ fontSize: 14, fontWeight: '800', color: AT.plumMid }}>Skip</Text>
        </Pressable>
      </View>

      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        style={{ flex: 1 }}
      >
        {CARDS.map((c, i) => (
          <View
            key={i}
            style={{
              width: SCREEN_W - 36, // matches the Screen's 18px h-padding
              alignItems: 'center',
              justifyContent: 'center',
              paddingHorizontal: 4,
              gap: 18,
            }}
          >
            <MascotSlot size={150} pose={c.pose} tone={c.tone} />
            <View style={{ minHeight: 130, alignItems: 'center', justifyContent: 'center' }}>
              {c.art}
            </View>
            <Text style={{ fontSize: 28, fontWeight: '900', letterSpacing: -0.4, color: AT.plum, textAlign: 'center' }}>
              {c.title}
            </Text>
            <Text style={{ fontSize: 16, color: AT.plumMid, textAlign: 'center', lineHeight: 23, paddingHorizontal: 16 }}>
              {c.body}
            </Text>
          </View>
        ))}
      </ScrollView>

      <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 8, paddingVertical: 14 }}>
        {CARDS.map((_, i) => (
          <View
            key={i}
            style={{
              width: i === idx ? 26 : 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: i === idx ? AT.coral : AT.creamDeep,
              borderWidth: AT.ol2,
              borderColor: AT.plum,
            }}
          />
        ))}
      </View>

      <Btn kind="primary" onPress={next} style={{ marginBottom: 18 }}>
        {idx === CARDS.length - 1 ? 'Let’s go →' : 'Next →'}
      </Btn>
    </Screen>
  );
}
