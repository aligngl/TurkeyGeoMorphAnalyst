<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.16" styleCategories="Symbology">
  <pipe>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="0" classificationMax="30">
      <rastershader>
        <colorrampshader colorRampType="DISCRETE" classificationMode="1" clip="0">
          <item alpha="255" value="3" label="&lt; 3 Çok kuru" color="#8c510a"/>
          <item alpha="255" value="6" label="3-6 Kuru yamaç" color="#d8b365"/>
          <item alpha="255" value="9" label="6-9 Az nemli" color="#f6e8c3"/>
          <item alpha="255" value="12" label="9-12 Orta nemli" color="#c7eae5"/>
          <item alpha="255" value="15" label="12-15 Nemli" color="#5ab4ac"/>
          <item alpha="255" value="18" label="15-18 Islak" color="#01665e"/>
          <item alpha="255" value="30" label="&gt; 18 Çok ıslak" color="#003c30"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
  </pipe>
</qgis>
