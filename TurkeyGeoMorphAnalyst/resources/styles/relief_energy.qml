<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.16" styleCategories="Symbology">
  <pipe>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="0" classificationMax="1000">
      <rastershader>
        <colorrampshader colorRampType="DISCRETE" classificationMode="1" clip="0">
          <item alpha="255" value="25" label="&lt; 25 m Çok düşük" color="#f7fcf0"/>
          <item alpha="255" value="75" label="25-75 m Düşük" color="#cae8c2"/>
          <item alpha="255" value="150" label="75-150 m Orta düşük" color="#7bcb91"/>
          <item alpha="255" value="300" label="150-300 m Orta yüksek" color="#2ca25f"/>
          <item alpha="255" value="500" label="300-500 m Yüksek" color="#006d2c"/>
          <item alpha="255" value="999" label="&gt; 500 m Çok yüksek" color="#00441b"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
  </pipe>
</qgis>
