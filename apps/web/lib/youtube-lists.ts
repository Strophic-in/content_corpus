// The Explore page's choices — countries, categories and their sub-categories —
// shared by the server (lib/youtube.ts) and the filter form in the browser.

/** "WW": Worldwide — the charts of WORLD merged (YouTube has no global chart). */
export const WORLDWIDE = "WW";
export const REGIONS: [string, string][] = [
  [WORLDWIDE, "🌍 Worldwide"],
  ["IN", "India"], ["US", "United States"], ["GB", "United Kingdom"], ["CA", "Canada"], ["AU", "Australia"],
  ["NZ", "New Zealand"], ["IE", "Ireland"], ["AE", "UAE"], ["SA", "Saudi Arabia"], ["SG", "Singapore"],
  ["MY", "Malaysia"], ["PH", "Philippines"], ["ID", "Indonesia"], ["PK", "Pakistan"], ["BD", "Bangladesh"],
  ["LK", "Sri Lanka"], ["NP", "Nepal"], ["NG", "Nigeria"], ["KE", "Kenya"], ["ZA", "South Africa"],
  ["EG", "Egypt"], ["DE", "Germany"], ["FR", "France"], ["ES", "Spain"], ["IT", "Italy"], ["NL", "Netherlands"],
  ["SE", "Sweden"], ["PL", "Poland"], ["TR", "Türkiye"], ["RU", "Russia"], ["BR", "Brazil"], ["MX", "Mexico"],
  ["AR", "Argentina"], ["CO", "Colombia"], ["JP", "Japan"], ["KR", "South Korea"], ["TW", "Taiwan"],
  ["HK", "Hong Kong"], ["TH", "Thailand"], ["VN", "Vietnam"],
];
// The big, widely watched charts Worldwide merges: 1 unit each.
export const WORLD = ["US", "IN", "GB", "CA", "AU", "PH", "NG", "ZA", "SG", "AE", "IE", "NZ"];

export const CATEGORIES: [string, string][] = [
  ["", "All"], ["25", "News & Politics"], ["28", "Science & Tech"], ["24", "Entertainment"], ["23", "Comedy"],
  ["17", "Sports"], ["20", "Gaming"], ["10", "Music"], ["26", "Howto & Style"], ["27", "Education"],
  ["22", "People & Blogs"], ["1", "Film & Animation"], ["2", "Autos"], ["15", "Pets & Animals"],
  ["19", "Travel"], ["29", "Nonprofits & Activism"],
];

/** Sub-categories: YouTube's charts have none, so each is a search inside its
 *  category for its own words (`|` is YouTube's OR), most viewed lately first. */
export const SUBCATEGORIES: Record<string, { id: string; name: string; q: string }[]> = {
  "28": [
    { id: "ai", name: "AI", q: "AI|artificial intelligence|ChatGPT|OpenAI|Gemini" },
    { id: "space", name: "Space", q: "space|NASA|ISRO|SpaceX|rocket|astronomy" },
    { id: "phones", name: "Smartphones", q: "smartphone|iPhone|Samsung Galaxy|Pixel|OnePlus" },
    { id: "gadgets", name: "Gadgets & reviews", q: "gadget|unboxing|tech review" },
    { id: "pc", name: "Computers & PC", q: "PC build|laptop|GPU|Nvidia|processor" },
    { id: "ev", name: "Electric vehicles", q: "electric vehicle|EV|Tesla|battery" },
    { id: "physics", name: "Physics", q: "physics|quantum|black hole|relativity" },
    { id: "bio", name: "Biology & health", q: "biology|medicine|human body|brain|DNA" },
    { id: "climate", name: "Climate & environment", q: "climate|environment|renewable energy" },
    { id: "robots", name: "Robotics", q: "robot|robotics|humanoid" },
    { id: "cyber", name: "Cybersecurity", q: "cybersecurity|hacking|scam|data breach" },
    { id: "code", name: "Coding", q: "programming|coding|developer|software" },
    { id: "inventions", name: "Inventions", q: "invention|engineering|how it is made" },
  ],
  "25": [
    { id: "world", name: "World news", q: "world news|international" },
    { id: "india", name: "India", q: "India news|Indian politics" },
    { id: "us", name: "US politics", q: "US politics|White House|Congress" },
    { id: "elections", name: "Elections", q: "election|polls|vote" },
    { id: "war", name: "War & conflict", q: "war|conflict|military|ceasefire" },
    { id: "economy", name: "Economy & markets", q: "economy|stock market|inflation|budget" },
    { id: "disasters", name: "Weather & disasters", q: "flood|earthquake|cyclone|storm|wildfire" },
    { id: "crime", name: "Crime & courts", q: "crime|court|verdict|arrest" },
    { id: "explained", name: "Explained", q: "explained|analysis" },
  ],
  "24": [
    { id: "movies", name: "Movies & trailers", q: "trailer|movie|box office" },
    { id: "series", name: "TV & web series", q: "web series|Netflix|Prime Video|season" },
    { id: "bollywood", name: "Bollywood", q: "Bollywood" },
    { id: "south", name: "South Indian cinema", q: "Tollywood|Kollywood|Telugu movie|Tamil movie" },
    { id: "hollywood", name: "Hollywood", q: "Hollywood|Marvel|DC" },
    { id: "celebs", name: "Celebrities", q: "celebrity|interview|red carpet" },
    { id: "reality", name: "Reality shows", q: "reality show|Bigg Boss|talent show" },
    { id: "kdrama", name: "K-drama & K-pop", q: "K-drama|K-pop|BTS|BLACKPINK" },
    { id: "anime", name: "Anime", q: "anime" },
  ],
  "23": [
    { id: "standup", name: "Stand-up", q: "stand up comedy" },
    { id: "sketch", name: "Sketches", q: "comedy sketch|funny skit" },
    { id: "pranks", name: "Pranks", q: "prank" },
    { id: "memes", name: "Memes", q: "memes|meme review" },
    { id: "roast", name: "Roasts", q: "roast" },
  ],
  "17": [
    { id: "cricket", name: "Cricket", q: "cricket|IPL|T20|test match" },
    { id: "football", name: "Football", q: "football|soccer|Premier League|Champions League" },
    { id: "basketball", name: "Basketball", q: "NBA|basketball" },
    { id: "f1", name: "Formula 1", q: "F1|Formula 1|Grand Prix" },
    { id: "tennis", name: "Tennis", q: "tennis|Wimbledon|US Open" },
    { id: "combat", name: "Combat sports", q: "UFC|boxing|WWE|MMA" },
    { id: "olympics", name: "Olympics & athletics", q: "Olympics|athletics|javelin|sprint" },
    { id: "kabaddi", name: "Kabaddi", q: "kabaddi|Pro Kabaddi" },
  ],
  "20": [
    { id: "minecraft", name: "Minecraft", q: "Minecraft" },
    { id: "gta", name: "GTA", q: "GTA|GTA 6" },
    { id: "battle", name: "Battle royale", q: "BGMI|PUBG|Free Fire|Fortnite|Warzone" },
    { id: "esports", name: "Esports", q: "esports|tournament|Valorant" },
    { id: "trailers", name: "Game trailers", q: "game trailer|gameplay reveal" },
    { id: "mobile", name: "Mobile games", q: "mobile game" },
  ],
  "10": [
    { id: "bollywood", name: "Bollywood songs", q: "Bollywood song|Hindi song" },
    { id: "punjabi", name: "Punjabi", q: "Punjabi song" },
    { id: "hiphop", name: "Hip-hop & rap", q: "rap|hip hop" },
    { id: "pop", name: "Pop", q: "pop song|official music video" },
    { id: "kpop", name: "K-pop", q: "K-pop" },
    { id: "lofi", name: "Lo-fi & chill", q: "lofi|chill" },
    { id: "covers", name: "Covers", q: "cover song|acoustic cover" },
  ],
  "26": [
    { id: "cooking", name: "Cooking", q: "recipe|cooking" },
    { id: "fashion", name: "Fashion", q: "fashion|outfit|haul" },
    { id: "beauty", name: "Beauty & makeup", q: "makeup|skincare|beauty" },
    { id: "fitness", name: "Fitness", q: "workout|fitness|gym" },
    { id: "diy", name: "DIY & crafts", q: "DIY|craft|hack" },
    { id: "home", name: "Home", q: "home decor|room makeover|cleaning" },
  ],
  "27": [
    { id: "history", name: "History", q: "history|ancient|empire" },
    { id: "money", name: "Money & finance", q: "personal finance|investing|money" },
    { id: "psychology", name: "Psychology", q: "psychology|mind|habits" },
    { id: "geography", name: "Geography", q: "geography|map|countries" },
    { id: "maths", name: "Maths", q: "maths|math" },
    { id: "exams", name: "Exams & study", q: "UPSC|JEE|NEET|study tips" },
    { id: "languages", name: "Languages", q: "learn English|language learning" },
    { id: "explainers", name: "Explainers", q: "explained|how does|why does" },
  ],
  "22": [
    { id: "vlogs", name: "Vlogs", q: "vlog" },
    { id: "dayinlife", name: "Day in the life", q: "day in the life" },
    { id: "podcasts", name: "Podcasts", q: "podcast" },
    { id: "motivation", name: "Motivation", q: "motivation|success story" },
    { id: "relationships", name: "Relationships", q: "relationship|dating|marriage" },
  ],
  "1": [
    { id: "animation", name: "Animation", q: "animation|animated short" },
    { id: "shortfilm", name: "Short films", q: "short film" },
    { id: "vfx", name: "VFX & behind the scenes", q: "VFX|behind the scenes" },
  ],
  "2": [
    { id: "cars", name: "Cars", q: "car review|new car" },
    { id: "bikes", name: "Bikes", q: "bike review|motorcycle" },
    { id: "ev", name: "Electric", q: "electric car|EV" },
    { id: "super", name: "Supercars", q: "supercar|hypercar|Lamborghini|Ferrari" },
  ],
  "15": [
    { id: "dogs", name: "Dogs", q: "dog|puppy" },
    { id: "cats", name: "Cats", q: "cat|kitten" },
    { id: "wildlife", name: "Wildlife", q: "wildlife|wild animals|safari" },
    { id: "ocean", name: "Ocean life", q: "ocean|shark|whale" },
    { id: "funny", name: "Funny animals", q: "funny animals" },
  ],
  "19": [
    { id: "vlogs", name: "Travel vlogs", q: "travel vlog" },
    { id: "food", name: "Street food", q: "street food" },
    { id: "places", name: "Hidden places", q: "hidden places|abandoned|unexplored" },
    { id: "budget", name: "Budget travel", q: "budget travel|cheap travel" },
  ],
};

export function subcategory(category: string, id: string) {
  return SUBCATEGORIES[category]?.find((s) => s.id === id) ?? null;
}
