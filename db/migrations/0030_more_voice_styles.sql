-- Sixteen more voice styles (prompts/voice_styles/): horror, true crime, movie trailer,
-- dramatic, nature documentary, mystery, storybook, Hindi kahani, funny, cringe,
-- deadpan, Gen Z, Hindi comedy, motivational, sports commentator, soft & calm. Switched
-- on for everyone; the owner switches off what doesn't fit (Settings → Voices).

alter table app_settings alter column voice_styles_enabled set default
  '{breaking_news,calm_explainer,conversational,hindi_anchor,documentary,nature_documentary,storyteller,mystery,kids_storybook,hindi_storyteller,horror,true_crime,movie_trailer,dramatic,somber,funny,cringe,deadpan,gen_z,hindi_comedy,energetic,motivational,sports_commentator,asmr_calm}';

update app_settings set voice_styles_enabled = array(select distinct unnest(voice_styles_enabled || array[
  'nature_documentary','mystery','kids_storybook','hindi_storyteller','horror','true_crime','movie_trailer','dramatic',
  'funny','cringe','deadpan','gen_z','hindi_comedy','motivational','sports_commentator','asmr_calm']));
