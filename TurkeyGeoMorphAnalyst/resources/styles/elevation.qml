<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.16" styleCategories="Symbology">
  <pipe>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="0" classificationMax="5200">
      <rasterTransparency/>
      <rastershader>
        <colorrampshader colorRampType="DISCRETE" classificationMode="1" clip="0">
          <item alpha="255" value="250" label="0-250 m" color="#2b4d9e"/>
          <item alpha="255" value="750" label="250-750 m" color="#4db87a"/>
          <item alpha="255" value="1500" label="750-1500 m" color="#e8d44d"/>
          <item alpha="255" value="2500" label="1500-2500 m" color="#c47b2b"/>
          <item alpha="255" value="3500" label="2500-3500 m" color="#8b4513"/>
          <item alpha="255" value="5200" label="3500 m ve üzeri" color="#ffffff"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
  </pipe>
</qgis>
