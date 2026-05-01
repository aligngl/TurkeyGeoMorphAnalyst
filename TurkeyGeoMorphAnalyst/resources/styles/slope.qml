<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.16" styleCategories="Symbology">
  <pipe>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="0" classificationMax="90">
      <rastershader>
        <colorrampshader colorRampType="DISCRETE" classificationMode="1" clip="0">
          <item alpha="255" value="2" label="0-2° Düz" color="#ffffb2"/>
          <item alpha="255" value="5" label="2-5° Çok az eğimli" color="#fed976"/>
          <item alpha="255" value="8" label="5-8° Az eğimli" color="#feb24c"/>
          <item alpha="255" value="15" label="8-15° Orta eğimli" color="#fd8d3c"/>
          <item alpha="255" value="30" label="15-30° Eğimli" color="#fc4e2a"/>
          <item alpha="255" value="45" label="30-45° Çok eğimli" color="#e31a1c"/>
          <item alpha="255" value="90" label="&gt;45° Sarp" color="#800026"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
  </pipe>
</qgis>
